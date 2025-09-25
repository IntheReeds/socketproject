import argparse, socket, json, sys, time

def timeStamp(): return time.strftime("%H:%M:%S")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manager-ip", default="127.0.0.1")
    parser.add_argument("--manager-port", type=int, default=5000)
    parser.add_argument("--my-ip", default="127.0.0.1")
    parser.add_argument("--my-m-port", type=int, default=5101)
    parser.add_argument("--my-c-port", type=int, default=5201)
    args = parser.parse_args()

    mgr = (args.manager_ip, args.manager_port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.my_ip, args.my_m_port))

    print(f"[{timeStamp()}] [PEER] ready. manager={mgr}, my m-port={args.my_m_port}", flush=True)



    for line in sys.stdin:
        if line.strip().startswith("register-disk"):
            parts = line.strip().split()
            if len(parts) != 5:
                print("Correct Usage: register-disk <name> <ip> <m-port> <c-port>")
                continue
            _, disk_name, ip, m_port, c_port = parts
            if not disk_name.isalpha() and len(disk_name) <= 15:
                print("Error: disk_name must be alphabetic and at most 15 characters long")
                continue
            if ip != args.my_ip:
                print("Erorr: IPV4 address must match with the peer process running ")
                continue
            msg = {
                "type": "register-disk",
                "disk_name": disk_name,
                "ipv4_addr": ip,
                "m_port": int(m_port),
                "c_port": int(c_port)
            }
            sock.sendto(json.dumps(msg).encode(), mgr)
            data, _ = sock.recvfrom(4096)
            print(f"[{timeStamp()}] [PEER] got reply {data.decode()}")
        elif line.strip().startswith("deregister-disk"):
            parts = line.strip().split()
            if len(parts) != 2:
                print("Correct usage: deregister-disk <disk-name>")
                continue
            _, disk_name = parts
            msg = {"type": "deregister-disk", "disk_name": disk_name}
            sock.sendto(json.dumps(msg).encode(), mgr)
            data, _ = sock.recvfrom(4096)
            print(f"[{timeStamp()}] [PEER] got reply {data.decode()}")

if __name__ == "__main__":
    main()