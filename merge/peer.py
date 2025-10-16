import argparse, socket, json, sys, time, threading, math,operator
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
            if not user_name.isalpha() and len(user_name) <= 15:
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
            print(f"[{timeStamp()}] [PEER] got reply {data.decode()}")
            reply = json.loads(data.decode())
            if(reply.get("code") == "Success") :
                reply = json.loads(data.decode())
                print(json.dumps(reply["state"]))
                
            #COPY
        elif line.strip().startswith("copy"): 
            parts = line.strip().split()
            if len(parts) !=4:
                print("Correct usage: copy <filename> <author>")
                continue
            _, file_name, file_size, owner = parts
            msg = {
                "type": "copy",
                "dss_name": file_name,
                "file_size": file_size,
                "owner": owner
            }
            mgr_sock.sendto(json.dumps(msg).encode(), mgr)
            print(f"[{timeStamp()}] [PEER] Sent copy request for {file_name}")

            data, _ = mgr_sock.recvfrom(4096)
            reply = json.loads(data.decode())
            print(f"[{timeStamp()}] [PEER] Received reply: {json.dumps(reply)}")

            if reply.get("code") == "FAILURE":
                print(f"[{timeStamp()}] [PEER] Copy failed: {reply.get('reason')}")
                continue
            
            dss_name = reply["dss_name"]
            n = reply["n"]
            stripping_unit = reply["stripping_unit"]
            disks = reply["disks"]
    
            print(f"[{timeStamp()}] [PEER] Starting copy to DSS {dss_name} with {n} disks")

            file_data = ((b"ABCDEFGHIJKLMNOPQRSTUVWXYZ") * 19) + b"ABCD" #TEST FILE DATA
            file_data = file_data[:500]
            data_per_stripe = (n - 1) * stripping_unit
            
            num_stripes = math.ceil(len(file_data) / data_per_stripe)
            for stripe_index in range(num_stripes): #starts the stripping
                start = stripe_index * data_per_stripe
                end = start + data_per_stripe
                stripe_data = file_data[start:end].ljust(data_per_stripe, b'\x00')

                # Split stripe into data blocks
                data_blocks = [stripe_data[i:i + stripping_unit] for i in range(0, len(stripe_data), stripping_unit)]

                # Create the parity block
                block_size = len(data_blocks[0])
                parity = bytearray(block_size)
                for i in range(block_size):
                    acc = 0
                    for block in data_blocks:
                        acc ^= block[i]
                    parity[i] = acc
                parity_block = bytes(parity)

                # Determine parity disk which should rotate per stripe
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
            done_msg = {"type": "copy-complete", "file_size" : file_size, "file_name": file_name, "owner": owner, "dss_name": dss_name}
            mgr_sock.sendto(json.dumps(done_msg).encode(), mgr)

    
            
           


def send_block_to_disk(file_name, disk, stripe_index, block_type, data_block):
    
    disk_name = disk["disk_name"]
    disk_ip = disk["ipv4_addr"]
    disk_c_port = int(disk["c_port"])  # ensure it's an int

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