#!/usr/bin/env python3
import argparse, json, socket, time, threading

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

    # Internal state
    state = {
        "users": {},            # user_name -> { user_name, ipv4_addr, m_port, c_port, when }
        "disks": {},            # disk_name -> { disk_name, ipv4_addr, m_port, c_port, state, when, dss_name? }
        "dss": {},              # dss_name  -> { disks: [disk_name...], stripping_unit: int, files?: {file_name->{size,owner}} }
        "_lock": None,          # critical section: { op: "copy"|"disk-failure"|"decommission", dss: str, user: str }
        "_reads": {}            # dss_name -> set(user_names) for in-progress reads
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

        # Global critical section gate: when a two-phase op is active, only its completion message is allowed
        if state["_lock"] is not None:
            op = state["_lock"].get("op")
            dss_locked = state["_lock"].get("dss")
            user_locked = state["_lock"].get("user")
            msg_type = msg.get("type")
            allowed = False
            if op == "copy" and msg_type == "copy-complete" and msg.get("dss_name") == dss_locked and msg.get("owner") == user_locked:
                allowed = True
            elif op == "disk-failure" and msg_type == "recovery-complete" and msg.get("dss_name") == dss_locked and msg.get("user_name") == user_locked:
                allowed = True
            elif op == "decommission" and msg_type == "decommission-complete" and msg.get("dss_name") == dss_locked and msg.get("user_name") == user_locked:
                allowed = True
            if not allowed:
                reply = {"type": f"{msg_type}-reply", "code": "FAILURE", "reason": "critical section in progress"}
                sock.sendto(json.dumps(reply).encode(), src)
                print(f"[{timeStamp()}] [MANAGER] REJECT (locked {op} on {dss_locked}) -> {reply}")
                continue

        # Dispatch by message type (inside while-loop)
        msg_type = msg.get("type")
        if msg_type == "register-user":
            #Message received
            user_name = msg.get("user_name")
            if user_name in state["users"]:
                reply = {"type": "register-user-reply", "code": "FAILURE",
                        "reason": f"username '{user_name}' already registered"}
                reply_addr = src
                sock.sendto(json.dumps(reply).encode(), reply_addr)
                print(f"[{timeStamp()}] [MANAGER] DUP USERNAME -> {reply}", flush=True)
                continue
            m_port = msg.get("m_port")
            if any(u["m_port"] == m_port for u in state["users"].values()):
                reply = {"type": "register-user-reply", "code": "FAILURE",
                        "reason": f"m_port {m_port} already in use"}
                reply_addr = src
                sock.sendto(json.dumps(reply).encode(), reply_addr)
                print(f"[{timeStamp()}] [MANAGER] DUP M_PORT -> {reply}", flush=True)
                continue
            c_port = msg.get("c_port")
            if any(u["c_port"] == c_port for u in state["users"].values()):
                reply = {"type": "register-user-reply", "code": "FAILURE",
                        "reason": f"c_port {c_port} already in use"}
                reply_addr = src
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

        elif msg_type == "register-disk":
            #Message received
            disk_name = msg.get("disk_name")
            if disk_name in state["disks"]:
                reply = {"type": "register-disk-reply", "code": "FAILURE",
                        "reason": f"disk_name '{disk_name}' already registered"}
                reply_addr = src
                sock.sendto(json.dumps(reply).encode(), reply_addr)
                print(f"[{timeStamp()}] [MANAGER] DUP DISKNAME -> {reply}", flush=True)
                continue
            m_port = msg.get("m_port")
            if any(u["m_port"] == m_port for u in state["disks"].values()):
                reply = {"type": "register-disk-reply", "code": "FAILURE",
                        "reason": f"m_port {m_port} already in use"}
                reply_addr = src
                sock.sendto(json.dumps(reply).encode(), reply_addr)
                print(f"[{timeStamp()}] [MANAGER] DUP M_PORT -> {reply}", flush=True)
                continue
            c_port = msg.get("c_port")
            if any(u["c_port"] == c_port for u in state["disks"].values()):
                reply = {"type": "register-disk-reply", "code": "FAILURE",
                        "reason": f"c_port {c_port} already in use"}
                reply_addr = src
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

        elif msg_type == "configure-dss":
            dss_name = msg.get("dss_name")
            n = int(msg.get("n", 0))
            su = int(msg.get("stripping_unit", 0))

            # validation for dss
            if not (dss_name and dss_name.isalpha() and len(dss_name) <= 15):
                reply = {"type": "configure-dss-reply", "code": "FAILURE", "reason": "invalid dss_name"}
            elif n < 3:
                reply = {"type": "configure-dss-reply", "code": "FAILURE", "reason": "n must be >= 3"}
            elif dss_name in state["dss"]:
                reply = {"type": "configure-dss-reply", "code": "FAILURE", "reason": "DSS already exists with that name"}
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
                    state["dss"][dss_name] = {"disks": chosen, "stripping_unit": su}
                    reply = {"type": "configure-dss-reply", "code": "SUCCESS", "reason": ""}

            sock.sendto(json.dumps(reply).encode(), src)

        elif msg_type == "deregister-user":          #DEREGISTER USER
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

        elif msg_type == "deregister-disk":        #DEREGISTER DISK
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
            # cannot deregister if part of a DSS
            if state["disks"][disk_name].get("state") == "InDSS":
                reply = {"type":"deregister-disk-reply","code":"FAILURE","reason":"disk is part of a DSS"}
                sock.sendto(json.dumps(reply).encode(), src)
                print(f"[{timeStamp()}] [MANAGER] DEREG -> {reply}", flush=True)
                continue

            del state["disks"][disk_name]
            reply = {"type":"deregister-disk-reply","code":"SUCCESS","reason":""}
            sock.sendto(json.dumps(reply).encode(), src)
            print(f"[{timeStamp()}] [MANAGER] DEREG -> {reply}", flush=True)
            print(f"[{timeStamp()}] [MANAGER] current disks: {state['disks']}", flush=True)

        elif msg_type == "ls":       #LS
            if not state["dss"]:
                reply = {"type":"ls-reply","code":"FAILURE","reason":"no DSS configured"}
                sock.sendto(json.dumps(reply).encode(), src)
                print(f"[{timeStamp()}] [MANAGER] LS -> {reply}", flush=True)
                continue
            # Build a structured listing
            dss_list = []
            for dss_name, info in state["dss"].items():
                disks_ordered = info.get("disks", [])
                files_map = info.get("files", {})
                files_list = [
                    {"file_name": fn, "file_size": meta.get("size", 0), "owner": meta.get("owner", "")}
                    for fn, meta in files_map.items()
                ]
                dss_list.append({
                    "dss_name": dss_name,
                    "n": len(disks_ordered),
                    "disks": disks_ordered,
                    "striping_unit": info.get("stripping_unit", 0),
                    "files": files_list
                })
            reply = {"type":"ls-reply","code": "SUCCESS", "dss": dss_list}
            sock.sendto(json.dumps(reply).encode(), src)
            print(f"[{timeStamp()}] [MANAGER] LS -> {reply}", flush=True)

        elif msg_type == "copy":
            # Start two-phase copy in a critical section
            if not state["dss"]:
                reply = {"type": "copy-reply",  "code": "FAILURE", "reason": "no DSS configured"}
                sock.sendto(json.dumps(reply).encode(), src)
                print(f"[{timeStamp()}] [MANAGER] COPY FAILURE (no DSS)")
                continue
            if state["_lock"] is not None:
                reply = {"type": "copy-reply",  "code": "FAILURE", "reason": "critical section in progress"}
                sock.sendto(json.dumps(reply).encode(), src)
                continue
            # Select a DSS (first configured)
            dss_name, dss_info = next(iter(state["dss"].items()))
            n = len(dss_info["disks"])
            su = dss_info["stripping_unit"]
            # Acquire lock for this copy
            owner = msg.get("owner", "")
            state["_lock"] = {"op": "copy", "dss": dss_name, "user": owner}
            # Build reply with disk info
            reply = {"type": "copy-reply", "code": "SUCCESS", "dss_name": dss_name, "n": n, "striping_unit": su, "disks": []}
            for disk_name in dss_info["disks"]:
                disk_info = state["disks"][disk_name]
                reply["disks"].append({
                    "disk_name": disk_name,
                    "ipv4_addr": disk_info["ipv4_addr"],
                    "c_port": disk_info["c_port"]
                })
            sock.sendto(json.dumps(reply).encode(), src)
            print(f"[{timeStamp()}] [MANAGER] COPY PHASE1 -> {reply}")

        elif msg_type == "copy-complete":
            file_name = msg.get("file_name")
            owner = msg.get("owner")
            dss_name = msg.get("dss_name")
            file_size = int(msg.get("file_size", 0))
            # Ensure lock matches
            if not state["_lock"] or state["_lock"].get("op") != "copy" or state["_lock"].get("dss") != dss_name or state["_lock"].get("user") != owner:
                reply = {"type": "copy-complete-reply", "code": "FAILURE", "reason": "no matching copy in progress"}
                sock.sendto(json.dumps(reply).encode(), src)
                continue
            dss_info = state["dss"][dss_name]
            dss_info.setdefault("files", {})[file_name] = {
                "size": file_size,
                "owner": owner
            }
            state["_lock"] = None
            reply = {"type": "copy-complete-reply", "code": "SUCCESS"}
            sock.sendto(json.dumps(reply).encode(), src)
            print(f"[{timeStamp()}] [MANAGER] Copy complete recorded for {file_name}")

        elif msg_type == "read":
            dss_name = msg.get("dss_name")
            file_name = msg.get("file_name")
            user_name = msg.get("user_name")
            if not state["dss"] or dss_name not in state["dss"]:
                reply = {"type":"read-reply","code":"FAILURE","reason":"no DSS configured or unknown dss"}
                sock.sendto(json.dumps(reply).encode(), src)
                continue
            dss_info = state["dss"][dss_name]
            files = dss_info.get("files", {})
            if file_name not in files:
                reply = {"type":"read-reply","code":"FAILURE","reason":"file not found on DSS"}
                sock.sendto(json.dumps(reply).encode(), src)
                continue
            if files[file_name].get("owner") != user_name:
                reply = {"type":"read-reply","code":"FAILURE","reason":"user not owner of file"}
                sock.sendto(json.dumps(reply).encode(), src)
                continue
            # record in-progress read
            state["_reads"].setdefault(dss_name, set()).add(user_name)
            reply = {"type":"read-reply","code":"SUCCESS","file_size": files[file_name]["size"],
                     "dss_name": dss_name, "n": len(dss_info["disks"]), "striping_unit": dss_info["stripping_unit"], "disks": []}
            for disk_name in dss_info["disks"]:
                disk_info = state["disks"][disk_name]
                reply["disks"].append({"disk_name": disk_name, "ipv4_addr": disk_info["ipv4_addr"], "c_port": disk_info["c_port"]})
            sock.sendto(json.dumps(reply).encode(), src)
            print(f"[{timeStamp()}] [MANAGER] READ PHASE1 -> {reply}")

        elif msg_type == "read-complete":
            dss_name = msg.get("dss_name")
            user_name = msg.get("user_name")
            readers = state["_reads"].get(dss_name, set())
            if user_name in readers:
                readers.remove(user_name)
                if not readers:
                    state["_reads"].pop(dss_name, None)
                reply = {"type":"read-complete-reply","code":"SUCCESS"}
            else:
                reply = {"type":"read-complete-reply","code":"FAILURE","reason":"no matching read in progress"}
            sock.sendto(json.dumps(reply).encode(), src)
            print(f"[{timeStamp()}] [MANAGER] READ COMPLETE -> {reply}")

        elif msg_type == "disk-failure":
            dss_name = msg.get("dss_name")
            user_name = msg.get("user_name")
            if dss_name not in state["dss"]:
                reply = {"type":"disk-failure-reply","code":"FAILURE","reason":"unknown DSS"}
                sock.sendto(json.dumps(reply).encode(), src)
                continue
            # cannot start if reads in progress
            if state["_reads"].get(dss_name):
                reply = {"type":"disk-failure-reply","code":"FAILURE","reason":"read in progress on DSS"}
                sock.sendto(json.dumps(reply).encode(), src)
                continue
            if state["_lock"] is not None:
                reply = {"type":"disk-failure-reply","code":"FAILURE","reason":"critical section in progress"}
                sock.sendto(json.dumps(reply).encode(), src)
                continue
            dss_info = state["dss"][dss_name]
            # lock
            state["_lock"] = {"op":"disk-failure","dss": dss_name, "user": user_name}
            files_map = dss_info.get("files", {})
            files_list = [
                {"file_name": fn, "file_size": meta.get("size", 0), "owner": meta.get("owner", "")}
                for fn, meta in files_map.items()
            ]
            # include full disk contact info
            disks_detailed = []
            for dn in dss_info["disks"]:
                di = state["disks"].get(dn, {})
                disks_detailed.append({
                    "disk_name": dn,
                    "ipv4_addr": di.get("ipv4_addr"),
                    "c_port": di.get("c_port"),
                })
            reply = {"type":"disk-failure-reply","code":"SUCCESS","dss_name": dss_name,
                     "n": len(dss_info["disks"]), "striping_unit": dss_info["stripping_unit"],
                     "disks": disks_detailed, "files": files_list}
            sock.sendto(json.dumps(reply).encode(), src)
            print(f"[{timeStamp()}] [MANAGER] DISK-FAIL PHASE1 -> {reply}")

        elif msg_type == "recovery-complete":
            dss_name = msg.get("dss_name")
            user_name = msg.get("user_name")
            if state["_lock"] and state["_lock"].get("op") == "disk-failure" and state["_lock"].get("dss") == dss_name and state["_lock"].get("user") == user_name:
                state["_lock"] = None
                reply = {"type":"recovery-complete-reply","code":"SUCCESS"}
            else:
                reply = {"type":"recovery-complete-reply","code":"FAILURE","reason":"no matching disk-failure in progress"}
            sock.sendto(json.dumps(reply).encode(), src)
            print(f"[{timeStamp()}] [MANAGER] DISK-FAIL COMPLETE -> {reply}")

        elif msg_type == "decommission-dss":
            dss_name = msg.get("dss_name")
            user_name = msg.get("user_name")
            if dss_name not in state["dss"]:
                reply = {"type":"decommission-dss-reply","code":"FAILURE","reason":"unknown DSS"}
                sock.sendto(json.dumps(reply).encode(), src)
                continue
            if state["_lock"] is not None:
                reply = {"type":"decommission-dss-reply","code":"FAILURE","reason":"critical section in progress"}
                sock.sendto(json.dumps(reply).encode(), src)
                continue
            # lock
            dss_info = state["dss"][dss_name]
            state["_lock"] = {"op":"decommission","dss": dss_name, "user": user_name}
            reply = {"type":"decommission-dss-reply","code":"SUCCESS","dss_name": dss_name,
                     "n": len(dss_info["disks"]), "striping_unit": dss_info["stripping_unit"],
                     "disks": dss_info["disks"]}
            sock.sendto(json.dumps(reply).encode(), src)
            print(f"[{timeStamp()}] [MANAGER] DECOM PHASE1 -> {reply}")

        elif msg_type == "decommission-complete":
            dss_name = msg.get("dss_name")
            user_name = msg.get("user_name")
            if not state["_lock"] or state["_lock"].get("op") != "decommission" or state["_lock"].get("dss") != dss_name or state["_lock"].get("user") != user_name:
                reply = {"type":"decommission-complete-reply","code":"FAILURE","reason":"no matching decommission in progress"}
                sock.sendto(json.dumps(reply).encode(), src)
                continue
            # free disks and remove DSS
            disks = state["dss"][dss_name]["disks"]
            for dn in disks:
                if dn in state["disks"]:
                    state["disks"][dn]["state"] = "Free"
                    state["disks"][dn].pop("dss_name", None)
            state["dss"].pop(dss_name, None)
            state["_lock"] = None
            reply = {"type":"decommission-complete-reply","code":"SUCCESS"}
            sock.sendto(json.dumps(reply).encode(), src)
            print(f"[{timeStamp()}] [MANAGER] DECOM COMPLETE -> {reply}")

        else:
            print(f"[{timeStamp()}] [MANAGER] Unknown type: {msg.get('type')}", flush=True)
        


def handle_copy(msg, src, sock, state) :
    file_name = msg.get("file_name")
    file_size = int(msg.get("file_size", 0))
    owner = msg.get("owner")
    if not state["dss"]:
        reply = {"type": "copy-reply",  "code": "FAILURE", "reason": "no DSS configured"}
        sock.sendto(json.dumps(reply).encode(), src)
        print(f"[{timeStamp()}] [MANAGER] COPY FAILURE (no DSS)")
        return
    
    dss_name, dss_info = next(iter(state["dss"].items()))
    n = len(dss_info["disks"])
    su = dss_info["stripping_unit"]

    reply = {"type": "copy-reply", "code": "SUCCESS", "dss_name": dss_name, "n": n, "stripping_unit": su, "disks": []}

    for disk_name in dss_info["disks"]:
        disk_info = state["disks"][disk_name]
        reply["disks"].append({
            "disk_name": disk_name,
            "ipv4_addr": disk_info["ipv4_addr"],
            "c_port": disk_info["c_port"]
        })

    sock.sendto(json.dumps(reply).encode(), src)
    print(f"[{timeStamp()}] [MANAGER] Sent DSS info for copy to {src}")
    return





if __name__ == "__main__":
    main()
