import argparse, socket, json, sys, time,threading

def timeStamp(): return time.strftime("%H:%M:%S")

def listen_on_c_port(sock, storage):
    #listen to peer reads and writes
    while True:
        data, addr = sock.recvfrom(4096)
        try:
            msg = json.loads(data.decode())
        except Exception:
            print(f"[{timeStamp()}] [DISK] Invalid JSON", flush=True)
            continue

        msg_type = msg.get("type")

        if msg_type == "write-block":
            file_name = msg["file_name"]
            stripe = msg["stripe_index"]
            block_type = msg["block_type"]
            block_size = msg["block_size"]
            encoded_data = msg["data"]  # Data sent as string

            # Convert back to bytes for preview
            block_data = encoded_data.encode("latin1") 

            print(f"[{timeStamp()}] [DISK] Received {block_type} block for {file_name}, "
                f"stripe {stripe} ({block_size}B)")

            # store block in storage
            if file_name not in storage:
                storage[file_name] = []
            storage[file_name].append({
                "stripe": stripe,
                "block_type": block_type,
                "size": block_size,
                "data": block_data #shouldnt need this after i get read to work
            })

            print(f"[{timeStamp()}] [DISK] Stored block for {file_name} "
                f"({len(storage[file_name])} total)", flush=True)

        elif msg_type == "read-block":
            file_name = msg.get("file_name")
            stripe_index = msg.get("stripe_index")

            if file_name not in storage:
                reply = {"type": "read-block-reply", "code": "FAILURE", "reason": "file not found"}
            else:
                # Find the specific block for this stripe
                found = None
                for blk in storage[file_name]:
                    if blk["stripe"] == stripe_index:
                        found = blk
                        break

                if found:
                    reply = {
                        "type": "read-block-reply",
                        "code": "SUCCESS",
                        "file_name": file_name,
                        "stripe_index": stripe_index,
                        "block_type": found["block_type"],
                        "data": found["data"].decode("latin1")
                    }
                else:
                    reply = {"type": "read-block-reply", "code": "FAILURE", "reason": "stripe not found"}

            sock.sendto(json.dumps(reply).encode(), addr)
            print(f"[{timeStamp()}] [DISK] Sent read-block-reply for {file_name}, stripe {stripe_index}")
        elif msg_type == "fail":
            # wipe all stored blocks
            wiped_files = list(storage.keys())
            storage.clear()
            reply = {"type": "fail-complete", "code": "SUCCESS", "wiped_files": wiped_files}
            sock.sendto(json.dumps(reply).encode(), addr)
            print(f"[{timeStamp()}] [DISK] FAILURE simulated, wiped {len(wiped_files)} files")
        else:
            print(f"[{timeStamp()}] [DISK] Unknown msg type: {msg_type}", flush=True)

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

    storage = {}
    # Create UDP socket and bind to m-port
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.my_ip, args.my_m_port))

    print(f"[{timeStamp()}] [DISK] ready. manager={mgr}, my m-port={args.my_m_port}", flush=True)

    c_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    c_sock.bind((args.my_ip, args.my_c_port))

    print(f"[{timeStamp()}] [DISK] listening on {args.my_ip}:{args.my_c_port}", flush=True)

    threading.Thread(target=listen_on_c_port, args=(c_sock, storage), daemon=True).start()



    for line in sys.stdin:
        if line.strip().startswith("register-disk"):    #REGISTER DISK
            parts = line.strip().split()
            if len(parts) != 5:
                print("Correct Usage: register-disk <name> <ip> <m-port> <c-port>")
                continue
            _, disk_name, ip, m_port, c_port = parts
            if not (disk_name.isalpha() and len(disk_name) <= 15):    #check if disk name is valid
                print("Error: disk_name must be alphabetic and at most 15 characters long")
                continue
            if ip != args.my_ip:    #check if ip matches
                print("Error: IPV4 address must match with the peer process running ")
                continue
            # save info
            msg = {
                "type": "register-disk",
                "disk_name": disk_name,
                "ipv4_addr": ip,
                "m_port": int(m_port),
                "c_port": int(c_port)
            }
            sock.sendto(json.dumps(msg).encode(), mgr)
            data, _ = sock.recvfrom(4096)
            print(f"[{timeStamp()}] [DISK] got reply {data.decode()}")
        elif line.strip().startswith("deregister-disk"):    #DEREGISTER DISK
            parts = line.strip().split()
            if len(parts) != 2:                 #check if correct number of arguments
                print("Correct usage: deregister-disk <disk-name>")
                continue
            _, disk_name = parts
            msg = {"type": "deregister-disk", "disk_name": disk_name}
            sock.sendto(json.dumps(msg).encode(), mgr)
            data, _ = sock.recvfrom(4096)
            print(f"[{timeStamp()}] [DISK] got reply {data.decode()}")
        elif line.strip() == "debug-storage":
            print(f"\n[{timeStamp()}] [DISK] DEBUG STORAGE CONTENTS:")
            for fname, blocks in storage.items():
                print(f"  File: {fname}")
                for blk in blocks:
                    data_bytes = blk.get('data', b'')
                    preview = ' '.join(f"{b:02x}" for b in data_bytes[:16])
                    print(f"    Stripe {blk['stripe']} [{blk['block_type']}]: {blk['size']}B, Data preview: {preview}")
            print()


if __name__ == "__main__":
    main()
