import argparse, socket, json, sys, time

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
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.my_ip, args.my_m_port))

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
            sock.sendto(json.dumps(msg).encode(), mgr)
            data, _ = sock.recvfrom(4096)
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
            sock.sendto(json.dumps(msg).encode(), mgr)
            data, _ = sock.recvfrom(4096)
            print(f"[{timeStamp()}] [PEER] got reply {data.decode()}")
        elif line.strip().startswith("deregister-user"):    #DEREGISTER USER
            parts = line.strip().split()
            if len(parts) != 2:
                print("Correct usage: deregister-user <name>")
                continue
            _, user_name = parts
            # save info
            msg = {"type": "deregister-user", "user_name": user_name}
            sock.sendto(json.dumps(msg).encode(), mgr)
            data, _ = sock.recvfrom(4096)
            print(f"[{timeStamp()}] [PEER] got reply {data.decode()}")

if __name__ == "__main__":
    main()