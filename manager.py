#!/usr/bin/env python3
import argparse, json, socket, time

RECV_BYTES = 4096

def timeStamp(): return time.strftime("%H:%M:%S")

def main():
    """
    Main loop for the manager.
    Listens for UDP messages from users and disks, processes them, and maintains state.
    """
    ap = argparse.ArgumentParser() #Argument Parser 
    ap.add_argument("--bind", default="0.0.0.0") 
    ap.add_argument("--port", type=int, required=True)
    args = ap.parse_args()

    # Initial state
    state = {                   
        "users": {},
        "disks": {},
        "dss": {} 
     }  


    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #UDP Socket
    sock.bind((args.bind, args.port)) #Binding to address and port
    print(f"[{timeStamp()}] [MANAGER] listening on {args.bind}:{args.port}", flush=True) 

    while True:
        data, src = sock.recvfrom(RECV_BYTES)   #Receive data from socket
        try:
            msg = json.loads(data.decode("utf-8", "replace"))   #Decode JSON message
        except Exception:
            print(f"[{timeStamp()}] [MANAGER] Malformed JSON from {src}; ignoring", flush=True)
            continue

        print(f"[{timeStamp()}] [MANAGER] RECV {src} -> {msg}", flush=True)

        if msg.get("type") == "register-user":
            #Message received
            user_name = msg.get("user_name")
            if user_name in state["users"]:
                reply = {"type": "register-user-reply", "code": "FAILURE",
                        "reason": f"username '{user_name}' already registered"}
                # reply to sender's m-port if provided, else src
                reply_addr = (ip, m_port) if ip and m_port else src
                sock.sendto(json.dumps(reply).encode(), reply_addr)
                print(f"[{timeStamp()}] [MANAGER] DUP USERNAME -> {reply}", flush=True)
                continue
            m_port = msg.get("m_port")
            if any(u["m_port"] == m_port for u in state["users"].values()):
                # Error if m_port already in use
                reply = {"type": "register-user-reply", "code": "FAILURE",
                        "reason": f"m_port {m_port} already in use"}
                reply_addr = (ip, m_port) if ip and m_port else src 
                sock.sendto(json.dumps(reply).encode(), reply_addr) 
                print(f"[{timeStamp()}] [MANAGER] DUP M_PORT -> {reply}", flush=True)
                continue
            c_port = msg.get("c_port")
            if any(u["c_port"] == c_port for u in state["users"].values()):
                # Error if c_port already in use
                reply = {"type": "register-user-reply", "code": "FAILURE",
                        "reason": f"c_port {c_port} already in use"}
                reply_addr = (ip, m_port) if ip and m_port else src
                sock.sendto(json.dumps(reply).encode(), reply_addr)
                print(f"[{timeStamp()}] [MANAGER] DUP C_PORT -> {reply}", flush=True)
                continue
            # Record user information
            rec = {
                "user_name": user_name,
                "ipv4_addr": msg.get("ipv4_addr"),
                "m_port": msg.get("m_port"),
                "c_port": msg.get("c_port"),
                "when": time.time(),
            }
            if user_name:
                state["users"][user_name] = rec

            # Reply to the provided ip/m_port if present; else reply to source
            ip = msg.get("ipv4_addr")
            m_port = msg.get("m_port")
            reply_addr = (ip, int(m_port)) if ip and m_port else src

            reply = {"type": "register-user-reply", "code": "SUCCESS", "reason": ""}
            sock.sendto(json.dumps(reply).encode(), reply_addr)
            print(f"[{timeStamp()}] [MANAGER] SEND {reply_addr} -> {reply}", flush=True)
            print(f"[{timeStamp()}] [MANAGER] current users: {state['users']}")

        #REGISTER DISK
        elif msg.get("type") == "register-disk":
            #Message recieve
            disk_name = msg.get("disk_name")
            if disk_name in state["disks"]:
                reply = {"type": "register-disk-reply", "code": "FAILURE",
                        "reason": f"disk_name '{disk_name}' already registered"}
                # reply to sender's m-port if provided, else src
                reply_addr = (ip, m_port) if ip and m_port else src
                sock.sendto(json.dumps(reply).encode(), reply_addr)
                print(f"[{timeStamp()}] [MANAGER] DUP DISKNAME -> {reply}", flush=True)
                continue
            m_port = msg.get("m_port")
            if any(u["m_port"] == m_port for u in state["disks"].values()):
                reply = {"type": "register-disk-reply", "code": "FAILURE",
                        "reason": f"m_port {m_port} already in use"}
                reply_addr = (ip, m_port) if ip and m_port else src
                sock.sendto(json.dumps(reply).encode(), reply_addr)
                print(f"[{timeStamp()}] [MANAGER] DUP M_PORT -> {reply}", flush=True)
                continue
            c_port = msg.get("c_port")
            if any(u["c_port"] == c_port for u in state["disks"].values()):
                reply = {"type": "register-disk-reply", "code": "FAILURE",
                        "reason": f"c_port {c_port} already in use"}
                reply_addr = (ip, m_port) if ip and m_port else src
                sock.sendto(json.dumps(reply).encode(), reply_addr)
                print(f"[{timeStamp()}] [MANAGER] DUP C_PORT -> {reply}", flush=True)
                continue
            rec = {
                "disk_name": disk_name,
                "ipv4_addr": msg.get("ipv4_addr"),
                "m_port": msg.get("m_port"),
                "c_port": msg.get("c_port"),
                "state": "Free",
                "when": time.time(),
            }
            if disk_name:
                state["disks"][disk_name] = rec

            # Reply to the provided ip/m_port 
            ip = msg.get("ipv4_addr")
            m_port = msg.get("m_port")
            reply_addr = (ip, int(m_port)) if ip and m_port else src

            reply = {"type": "register-disk-reply", "code": "SUCCESS", "reason": ""}
            sock.sendto(json.dumps(reply).encode(), reply_addr)
            print(f"[{timeStamp()}] [MANAGER] SEND {reply_addr} -> {reply}", flush=True)
        elif msg.get("type") == "configure-dss":
            dss_name = msg.get("dss_name")
            n = int(msg.get("n", 0))
            su = int(msg.get("striping_unit", 0))

            # validation for dss
            if not (dss_name.isalpha() and len(dss_name) <= 15):
                reply = {"type": "configure-dss-reply", "code": "FAILURE", "reason": "invalid dss_name"}
            elif n < 3:
                reply = {"type": "configure-dss-reply", "code": "FAILURE", "reason": "n must be >= 3"}
            elif dss_name in state["dss"]:
                reply = {"type": "configure-dss-reply", "code": "FAILURE", "reason": "DSS already exists with that name"}
            #elif su < 128 or su > 1024*1024 :
                #reply = {"type": "configure-dss-reply", "code": "FAILURE", "reason": "invalid striping-unit"}
            else:
                # find n free disks
                free_disks = [d for d, rec in state["disks"].items() if rec["state"] == "Free"]
                if len(free_disks) < n:
                    reply = {"type": "configure-dss-reply", "code": "FAILURE", "reason": "not enough free disks"}
                else:
                    import random
                    chosen = random.sample(free_disks, n)
                    for d in chosen:
                        state["disks"][d]["state"] = "InDSS"
                        state["disks"][d]["dss_name"] = dss_name
                    state["dss"][dss_name] = {"disks": chosen, "striping_unit": su}
                    reply = {"type": "configure-dss-reply", "code": "SUCCESS", "reason": ""}

            sock.sendto(json.dumps(reply).encode(), src)
        elif msg.get("type") == "deregister-user":          #DEREGISTER USER
            user_name = msg.get("user_name")

            if user_name not in state["users"]:
                reply = {
                    "type": "deregister-user-reply",
                    "code": "FAILURE",
                    "reason": f"user '{user_name}' not found"
                }
            else:
                del state["users"][user_name]
                reply = {
                    "type": "deregister-user-reply",
                    "code": "SUCCESS",
                    "reason": ""
                }

            sock.sendto(json.dumps(reply).encode(), src)
            print(f"[{timeStamp()}] [MANAGER] DEREG -> {reply}", flush=True)
            print(f"[{timeStamp()}] [MANAGER] current users: {state['users']}")
        elif msg.get("type") == "deregister-disk":        #DEREGISTER DISK  
            disk_name = msg.get("disk_name")

            if not disk_name:
                reply = {"type":"deregister-disk-reply","code":"FAILURE","reason":"missing disk_name"}
                sock.sendto(json.dumps(reply).encode(), src)
                print(f"[{timeStamp()}] [MANAGER] DEREG -> {reply}", flush=True)
                continue

            # check existence
            if disk_name not in state["disks"]:
                reply = {"type":"deregister-disk-reply","code":"FAILURE",
                        "reason": f"disk '{disk_name}' not found"}
                sock.sendto(json.dumps(reply).encode(), src)
                print(f"[{timeStamp()}] [MANAGER] DEREG -> {reply}", flush=True)
                continue


            del state["disks"][disk_name]
            reply = {"type":"deregister-disk-reply","code":"SUCCESS","reason":""}
            sock.sendto(json.dumps(reply).encode(), src)
            print(f"[{timeStamp()}] [MANAGER] DEREG -> {reply}", flush=True)
            print(f"[{timeStamp()}] [MANAGER] current disks: {state['disks']}", flush=True)
        else:
            print(f"[{timeStamp()}] [MANAGER] Unknown type: {msg.get('type')}", flush=True)

if __name__ == "__main__":
    main()
