import argparse, socket, json, sys, time, threading, math, operator
from functools import reduce


def timeStamp(): return time.strftime("%H:%M:%S")

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--manager-ip", default="127.0.0.1")
    parser.add_argument("--manager-port", type=int, default=5000)
    parser.add_argument("--my-ip", default="127.0.0.1")
    parser.add_argument("--my-m-port", type=int, default=5101)
    parser.add_argument("--my-c-port", type=int, default=5201)
    args = parser.parse_args()

    mgr = (args.manager_ip, args.manager_port)

    # Create UDP socket and bind to m-port
    mgr_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    mgr_sock.bind((args.my_ip, args.my_m_port))

    print(f"[{timeStamp()}] [PEER] ready. manager={mgr}, my m-port={args.my_m_port}", flush=True)



    for line in sys.stdin:
        if line.strip().startswith("register-user"):        #REGISTER USER
            parts = line.strip().split()
            if len(parts) != 5:
                print("Correct Usage: register-user <name> <ip> <m-port> <c-port>")
                continue
            _, user_name, ip, m_port, c_port = parts
            if not (user_name.isalpha() and len(user_name) <= 15):
                print("Error: user_name must be alphabetic and at most 15 characters long")
                continue
            if ip != args.my_ip:
                print("Error: IPV4 address must match with the peer process running ")
                continue
            # save info
            msg = {
                "type": "register-user",
                "user_name": user_name,
                "ipv4_addr": ip,
                "m_port": int(m_port),
                "c_port": int(c_port)
            }
            mgr_sock.sendto(json.dumps(msg).encode(), mgr)
            data, _ = mgr_sock.recvfrom(4096)
            print(f"[{timeStamp()}] [PEER] got reply {data.decode()}")

        elif line.strip().startswith("configure-dss"):  #CONFIGURE DSS
            parts = line.strip().split()
            if len(parts) != 4:
                print("Correct Usage: configure-dss <dss-name> <n> <striping-unit>")
                continue
            _, dss_name, n, stripping_unit = parts
            # save info
            msg = {
                "type": "configure-dss",
                "dss_name": dss_name,
                "n": n,
                "stripping_unit": stripping_unit
            
            }
            mgr_sock.sendto(json.dumps(msg).encode(), mgr)
            data, _ = mgr_sock.recvfrom(4096)
            print(f"[{timeStamp()}] [PEER] got reply {data.decode()}")
        elif line.strip().startswith("deregister-user"):    #DEREGISTER USER
            parts = line.strip().split()
            if len(parts) != 2:
                print("Correct usage: deregister-user <name>")
                continue
            _, user_name = parts
            # save info
            msg = {"type": "deregister-user", "user_name": user_name}
            mgr_sock.sendto(json.dumps(msg).encode(), mgr)
            data, _ = mgr_sock.recvfrom(4096)
            print(f"[{timeStamp()}] [PEER] got reply {data.decode()}")
            #LS
        elif line.strip() == "ls":
            msg = {"type": "ls"}
            mgr_sock.sendto(json.dumps(msg).encode(), mgr)
            data, _ = mgr_sock.recvfrom(4096)
            reply = json.loads(data.decode())
            if reply.get("code") == "FAILURE":
                print(f"[{timeStamp()}] [PEER] ls failed: {reply.get('reason')}")
            else:
                # Pretty print DSS summary
                dss_list = reply.get("dss", [])
                if not dss_list:
                    print("No DSS configured")
                for d in dss_list:
                    name = d.get("dss_name")
                    n = d.get("n")
                    su = d.get("striping_unit")
                    disks = d.get("disks", [])
                    files = d.get("files", [])
                    print(f"DSS {name}:")
                    print(f"  n={n}, striping_unit={su}")
                    print(f"  disks: {', '.join(disks)}")
                    if files:
                        print("  files:")
                        for f in files:
                            print(f"    - {f.get('file_name')} (size={f.get('file_size')}, owner={f.get('owner')})")
                    else:
                        print("  files: <none>")
                
            #COPY
        elif line.strip().startswith("copy-to "):
            parts = line.strip().split()
            if len(parts) != 5:
                print("Correct usage: copy-to <dss-name> <file-name> <file-size> <owner>")
                continue
            _, target_dss, file_name, file_size, owner = parts
            msg = {
                "type": "copy",
                "dss_name": target_dss,
                "file_name": file_name,
                "file_size": int(file_size),
                "owner": owner
            }
            # drain stale
            try:
                mgr_sock.settimeout(0.0)
                while True:
                    try:
                        _discard, _ = mgr_sock.recvfrom(65535)
                    except (BlockingIOError, TimeoutError):
                        break
                    except Exception:
                        break
            finally:
                mgr_sock.settimeout(None)

            mgr_sock.sendto(json.dumps(msg).encode(), mgr)
            print(f"[{timeStamp()}] [PEER] Sent copy-to request for {file_name} to {target_dss}")

            # wait for copy-reply and then reuse the same flow as copy
            mgr_sock.settimeout(3.0)
            while True:
                try:
                    data, _ = mgr_sock.recvfrom(65535)
                except socket.timeout:
                    print(f"[{timeStamp()}] [PEER] Timeout waiting for copy-reply; retry command if needed")
                    continue
                reply = json.loads(data.decode())
                if reply.get("type") == "copy-reply":
                    break
                else:
                    print(f"[{timeStamp()}] [PEER] Ignoring unexpected reply type '{reply.get('type')}', waiting for copy-reply...")

            if reply.get("code") == "FAILURE":
                print(f"[{timeStamp()}] [PEER] Copy failed: {reply.get('reason')}")
                continue
            dss_name = reply.get("dss_name") or reply.get("dss-name") or reply.get("disk-array-name")
            n = reply.get("n")
            su = reply.get("stripping_unit") or reply.get("striping_unit") or reply.get("striping-unit")
            disks = reply.get("disks", [])
            if not (dss_name and n and su and disks):
                print(f"[{timeStamp()}] [PEER] Missing params in copy-reply: {reply}")
                continue

            with open(file_name, "rb") as f:
                file_data = f.read()
            data_per_stripe = (n - 1) * su
            num_stripes = math.ceil(len(file_data) / data_per_stripe)
            for stripe_index in range(num_stripes):
                start = stripe_index * data_per_stripe
                end = start + data_per_stripe
                stripe_data = file_data[start:end].ljust(data_per_stripe, b'\x00')
                data_blocks = [stripe_data[i:i + su] for i in range(0, len(stripe_data), su)]
                block_size = len(data_blocks[0])
                parity = bytearray(block_size)
                for i in range(block_size):
                    acc = 0
                    for block in data_blocks:
                        acc ^= block[i]
                    parity[i] = acc
                parity_block = bytes(parity)
                parity_disk_index = n - ((stripe_index % n) + 1)
                threads = []
                data_idx = 0
                for i, disk in enumerate(disks):
                    block_type = "PARITY" if i == parity_disk_index else "DATA"
                    block_data = parity_block if block_type == "PARITY" else data_blocks[data_idx]
                    if block_type == "DATA":
                        data_idx += 1
                    t = threading.Thread(target=send_block_to_disk, args=(file_name, disk, stripe_index, block_type, block_data))
                    t.start(); threads.append(t)
                for t in threads: t.join()
            done_msg = {"type": "copy-complete", "file_size" : int(file_size), "file_name": file_name, "owner": owner, "dss_name": dss_name}
            mgr_sock.sendto(json.dumps(done_msg).encode(), mgr)
            while True:
                try:
                    data, _ = mgr_sock.recvfrom(65535)
                except socket.timeout:
                    print(f"[{timeStamp()}] [PEER] Waiting for copy-complete-reply...")
                    continue
                ack = json.loads(data.decode())
                if ack.get("type") == "copy-complete-reply":
                    print(f"[{timeStamp()}] [PEER] copy-complete -> {ack.get('code')}")
                    break

        elif line.strip().startswith("copy"): 
            parts = line.strip().split()
            if len(parts) != 4:
                print("Correct usage: copy <file-name> <file-size> <owner>")
                continue
            _, file_name, file_size, owner = parts
            msg = {
                "type": "copy",
                "file_name": file_name,
                "file_size": int(file_size),
                "owner": owner
            }
            # drain any stale replies
            prev_timeout = None
            try:
                prev_timeout = mgr_sock.gettimeout()
            except Exception:
                prev_timeout = None
            try:
                mgr_sock.settimeout(0.0)
                while True:
                    try:
                        _discard, _ = mgr_sock.recvfrom(65535)
                    except (BlockingIOError, TimeoutError):
                        break
                    except Exception:
                        break
            finally:
                # restore to blocking
                mgr_sock.settimeout(None)

            mgr_sock.sendto(json.dumps(msg).encode(), mgr)
            print(f"[{timeStamp()}] [PEER] Sent copy request for {file_name}")


            mgr_sock.settimeout(3.0)
            while True:
                try:
                    data, _ = mgr_sock.recvfrom(65535)
                except socket.timeout:
                    print(f"[{timeStamp()}] [PEER] Timeout waiting for copy-reply; retry command if needed")
                    continue
                reply = json.loads(data.decode())
                rtype = reply.get("type")
                print(f"[{timeStamp()}] [PEER] Received reply: {json.dumps(reply)}")
                if rtype == "copy-reply":
                    break
                else:
                    print(f"[{timeStamp()}] [PEER] Ignoring unexpected reply type '{rtype}', waiting for copy-reply...")

            if reply.get("code") == "FAILURE":
                print(f"[{timeStamp()}] [PEER] Copy failed: {reply.get('reason')}")
                continue
            
            # accept both underscored and hyphenated keys
            dss_name = reply.get("dss_name") or reply.get("dss-name") or reply.get("disk-array-name")
            n = reply.get("n")
            stripping_unit = reply.get("stripping_unit") or reply.get("striping_unit") or reply.get("striping-unit")
            if stripping_unit is None:
                print(f"[{timeStamp()}] [PEER] Copy failed: missing strip(p)ing_unit in reply")
                continue
            disks = reply.get("disks", [])
    
            print(f"[{timeStamp()}] [PEER] Starting copy to DSS {dss_name} with {n} disks")

            with open(file_name, "rb") as f:
                file_data = f.read()
            data_per_stripe = (n - 1) * stripping_unit
            
            num_stripes = math.ceil(len(file_data) / data_per_stripe)
            for stripe_index in range(num_stripes): #starts the stripping
                start = stripe_index * data_per_stripe
                end = start + data_per_stripe
                stripe_data = file_data[start:end].ljust(data_per_stripe, b'\x00')

                # Split 
                data_blocks = [stripe_data[i:i + stripping_unit] for i in range(0, len(stripe_data), stripping_unit)]

                # parity block
                block_size = len(data_blocks[0])
                parity = bytearray(block_size)
                for i in range(block_size):
                    acc = 0
                    for block in data_blocks:
                        acc ^= block[i]
                    parity[i] = acc
                parity_block = bytes(parity)

                parity_disk_index = n - ((stripe_index % n) + 1)
                parity_disk = disks[parity_disk_index]

                print(f"\n[{timeStamp()}] [PEER] Stripe {stripe_index}: parity on {parity_disk['disk_name']}")

                threads = []
                data_idx = 0
                for i, disk in enumerate(disks):
                    block_type = "PARITY" if i == parity_disk_index else "DATA"
                    block_data = parity_block if block_type == "PARITY" else data_blocks[data_idx]
                    if block_type == "DATA":
                        data_idx += 1

                    # create thread to send block to each disk
                    t = threading.Thread(
                        target=send_block_to_disk, args=(file_name, disk, stripe_index, block_type, block_data))
                    t.start()
                    threads.append(t)

                for t in threads:
                    t.join()

            print(f"[{timeStamp()}] [PEER] Stripe written to all disks")
            done_msg = {"type": "copy-complete", "file_size" : int(file_size), "file_name": file_name, "owner": owner, "dss_name": dss_name}
            mgr_sock.sendto(json.dumps(done_msg).encode(), mgr)

            # drain and wait for the copy-complete-reply to clear manager lock
            while True:
                try:
                    data, _ = mgr_sock.recvfrom(65535)
                except socket.timeout:
                    print(f"[{timeStamp()}] [PEER] Waiting for copy-complete-reply...")
                    continue
                ack = json.loads(data.decode())
                atype = ack.get("type")
                if atype == "copy-complete-reply":
                    print(f"[{timeStamp()}] [PEER] copy-complete -> {ack.get('code')}")
                    break
                else:
                    # Ignore traffic
                    print(f"[{timeStamp()}] [PEER] Ignoring '{atype}' while waiting for copy-complete-reply")

        elif line.strip().startswith("read "):
            parts = line.strip().split()
            if len(parts) != 4:
                print("Correct usage: read <dss-name> <file-name> <user-name>")
                continue
            _, dss_name, file_name, user_name = parts
            req = {"type": "read", "dss_name": dss_name, "file_name": file_name, "user_name": user_name}
            mgr_sock.sendto(json.dumps(req).encode(), mgr)
            data, _ = mgr_sock.recvfrom(4096)
            reply = json.loads(data.decode())
            if reply.get("code") == "FAILURE":
                print(f"[{timeStamp()}] [PEER] read failed: {reply.get('reason')}")
                continue
            print(f"[{timeStamp()}] [PEER] read granted: size={reply.get('file_size')} bytes, disks={len(reply.get('disks', []))}")


            file_content = bytearray()
            disks = reply["disks"]
            n = reply.get("n")
            striping_unit = reply.get("striping_unit") or reply.get("striping-unit") or reply.get("stripping_unit")
            file_size = reply["file_size"]

            # Calculate stripes 
            stripe_size = (n - 1) * striping_unit
            total_stripes = (file_size + stripe_size - 1) // stripe_size

            for stripe_index in range(total_stripes):
                parity_disk_index = (n - 1) - (stripe_index % n)
                stripe_blocks = [None] * n

                print(f"[{timeStamp()}] [PEER] Reading stripe {stripe_index} (parity on disk {disks[parity_disk_index]['disk_name']})")

                for disk_index, disk in enumerate(disks):
                    disk_ip = disk["ipv4_addr"]
                    disk_c_port = disk["c_port"]
                    disk_name = disk["disk_name"]

                    block_req = {
                        "type": "read-block",
                        "file_name": file_name,
                        "stripe_index": stripe_index
                    }

                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    sock.settimeout(3)
                    try:
                        sock.sendto(json.dumps(block_req).encode(), (disk_ip, disk_c_port))
                        data, _ = sock.recvfrom(65535)
                        block_reply = json.loads(data.decode())

                        if block_reply.get("code") == "SUCCESS":
                            block_data = block_reply["data"].encode("latin1")
                            stripe_blocks[disk_index] = block_data
                            print(f"[{timeStamp()}] [PEER] Got block {disk_name} ({len(block_data)}B)")
                        else:
                            print(f"[{timeStamp()}] [PEER] {disk_name} failed: {block_reply.get('reason')}")
                    except socket.timeout:
                        print(f"[{timeStamp()}] [PEER] Timeout from {disk_name}")
                    finally:
                        sock.close()

                #missing data
                missing_indices = [i for i, b in enumerate(stripe_blocks) if b is None]
                if len(missing_indices) == 1:
                    missing = missing_indices[0]
                    print(f"[{timeStamp()}] [PEER] Reconstructing missing block for disk {disks[missing]['disk_name']}")
                    block_size = striping_unit
                    parity = bytearray(block_size)
                    for i, blk in enumerate(stripe_blocks):
                        if blk is not None:
                            for j in range(block_size):
                                parity[j] ^= blk[j]
                    stripe_blocks[missing] = bytes(parity)

                for i, blk in enumerate(stripe_blocks):
                    if i != parity_disk_index and blk is not None:
                        file_content.extend(blk)

            file_content = file_content[:file_size]
            print(f"[{timeStamp()}] [PEER] Reconstructed file {file_name}, total {len(file_content)} bytes.")

            
            print(f"[{timeStamp()}] [PEER] Finished reading {file_name} ({len(file_content)} bytes total)")
           

            done = {"type": "read-complete", "dss_name": dss_name, "user_name": user_name}
            mgr_sock.sendto(json.dumps(done).encode(), mgr)
            data, _ = mgr_sock.recvfrom(4096)
            rc = json.loads(data.decode())
            print(f"[{timeStamp()}] [PEER] read-complete -> {rc.get('code')}")
            output_filename = f"reconstructed_{file_name}"
            with open(output_filename, "wb") as f:
                f.write(file_content)

        elif line.strip().startswith("disk-failure "):
            parts = line.strip().split()
            if len(parts) != 3:
                print("Correct usage: disk-failure <dss-name> <user-name>")
                continue
            _, dss_name, user_name = parts
            req = {"type": "disk-failure", "dss_name": dss_name, "user_name": user_name}
            mgr_sock.sendto(json.dumps(req).encode(), mgr)
            data, _ = mgr_sock.recvfrom(4096)
            reply = json.loads(data.decode())
            if reply.get("code") == "FAILURE":
                print(f"[{timeStamp()}] [PEER] disk-failure denied: {reply.get('reason')}")
                continue
            # reply 
            n = reply.get("n")
            su = reply.get("stripping_unit") or reply.get("striping_unit") or reply.get("striping-unit")
            disks = reply["disks"]
            files = reply.get("files", [])

            # random disk to fail
            import random
            failed_index = random.randrange(0, n)
            failed_disk = disks[failed_index]
            print(f"[{timeStamp()}] [PEER] Failing disk index {failed_index}: {failed_disk['disk_name']}")

            # Send fail message
            fail_msg = {"type": "fail"}
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(3)
                s.sendto(json.dumps(fail_msg).encode(), (failed_disk["ipv4_addr"], int(failed_disk["c_port"])))
                try:
                    resp, _ = s.recvfrom(4096)
                    rj = json.loads(resp.decode())
                    if rj.get("type") != "fail-complete" or rj.get("code") != "SUCCESS":
                        print(f"[{timeStamp()}] [PEER] fail not acknowledged: {rj}")
                        continue
                except socket.timeout:
                    print(f"[{timeStamp()}] [PEER] fail timeout from {failed_disk['disk_name']}")
                    continue

            # reconstruct failed disk
            def read_block(disk, file_name, stripe_index):
                req = {"type": "read-block", "file_name": file_name, "stripe_index": stripe_index}
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s2:
                    s2.settimeout(3)
                    try:
                        s2.sendto(json.dumps(req).encode(), (disk["ipv4_addr"], int(disk["c_port"])))
                        data, _ = s2.recvfrom(1<<16)
                        r = json.loads(data.decode())
                        if r.get("code") == "SUCCESS":
                            return r["block_type"], r["data"].encode("latin1")
                    except socket.timeout:
                        pass
                return None, None

            # write block back to failed disk
            def write_block_to_failed(file_name, stripe_idx, block_type, data_bytes):
                msg = {
                    "type": "write-block",
                    "file_name": file_name,
                    "disk_name": failed_disk["disk_name"],
                    "stripe_index": stripe_idx,
                    "block_type": block_type,
                    "block_size": len(data_bytes),
                    "data": data_bytes.decode("latin1"),
                }
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s3:
                    s3.sendto(json.dumps(msg).encode(), (failed_disk["ipv4_addr"], int(failed_disk["c_port"])))

            for fmeta in files:
                fname = fmeta["file_name"]
                fsize = int(fmeta["file_size"])
                total_stripes = (fsize + (n-1)*su - 1) // ((n-1)*su)
                print(f"[{timeStamp()}] [PEER] Reconstructing file {fname}: {total_stripes} stripes")
                for stripe_idx in range(total_stripes):
                    # Determine which disk is parity
                    parity_disk_index = n - ((stripe_idx % n) + 1)
                    # read all other blocks in parallel
                    results = [None]*n
                    threads = []
                    def read_one(di):
                        if di == failed_index:
                            return
                        btype, bdata = read_block(disks[di], fname, stripe_idx)
                        results[di] = (btype, bdata)
                    for di in range(n):
                        if di == failed_index: continue
                        t = threading.Thread(target=read_one, args=(di,))
                        t.start(); threads.append(t)
                    for t in threads: t.join()

                    # XOR n-1 blocks
                    block_size = su
                    xor_buf = bytearray(block_size)
                    for di, tup in enumerate(results):
                        if di == failed_index or tup is None: continue
                        _, bdata = tup
                        if bdata is None:
                            continue
                        for j in range(min(block_size, len(bdata))):
                            xor_buf[j] ^= bdata[j]

 
                    rec_type = "PARITY" if failed_index == parity_disk_index else "DATA"
                    write_block_to_failed(fname, stripe_idx, rec_type, bytes(xor_buf))

            # reply
            done = {"type": "recovery-complete", "dss_name": dss_name, "user_name": user_name}
            mgr_sock.sendto(json.dumps(done).encode(), mgr)
            data, _ = mgr_sock.recvfrom(4096)
            rc = json.loads(data.decode())
            print(f"[{timeStamp()}] [PEER] recovery-complete -> {rc.get('code')}")

        elif line.strip().startswith("decommission-dss "):
            parts = line.strip().split()
            if len(parts) != 3:
                print("Correct usage: decommission-dss <dss-name> <user-name>")
                continue
            _, dss_name, user_name = parts
            req = {"type": "decommission-dss", "dss_name": dss_name, "user_name": user_name}
            mgr_sock.sendto(json.dumps(req).encode(), mgr)
            data, _ = mgr_sock.recvfrom(4096)
            reply = json.loads(data.decode())
            if reply.get("code") == "FAILURE":
                print(f"[{timeStamp()}] [PEER] decommission denied: {reply.get('reason')}")
                continue
            done = {"type": "decommission-complete", "dss_name": dss_name, "user_name": user_name}
            mgr_sock.sendto(json.dumps(done).encode(), mgr)
            data, _ = mgr_sock.recvfrom(4096)
            rc = json.loads(data.decode())
            print(f"[{timeStamp()}] [PEER] decommission-complete -> {rc.get('code')}")

def send_block_to_disk(file_name, disk, stripe_index, block_type, data_block):
    
    disk_name = disk["disk_name"]
    disk_ip = disk["ipv4_addr"]
    disk_c_port = int(disk["c_port"])  

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    message = {
        "type": "write-block",
        "file_name": file_name,
        "disk_name": disk_name,
        "stripe_index": stripe_index,
        "block_type": block_type,
        "block_size": len(data_block),
        "data": data_block.decode("latin1")  
    }

    sock.sendto(json.dumps(message).encode(), (disk_ip, disk_c_port))
    sock.close()

    print(f"[{timeStamp()}] [PEER] Sent {block_type} block ({len(data_block)} bytes) to {disk_name}:{disk_c_port}")

if __name__ == "__main__":
    main()
