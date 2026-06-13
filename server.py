import socket
import json
import uuid
import random
import os
import time
import logging
from datetime import datetime
import threading
import math

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("server_activity.log"),
        logging.StreamHandler()
    ]
)

HOST = '0.0.0.0'
PORT = 5555

WIDTH, HEIGHT = 800, 600
TANK_SPEED = 5
BULLET_SPEED = 10
MATCH_DURATION = 60
RECONNECT_TIMEOUT = 60

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    
    VOICE_PORT = PORT + 1
    voice_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    voice_sock.bind((HOST, VOICE_PORT))
    
    logging.info(f"=== UDP Game Server Started on {HOST}:{PORT} ===")
    
    clients = {} 
    rooms = {} 

    def send_to(addr, data_dict):
        try: sock.sendto(json.dumps(data_dict).encode('utf-8'), addr)
        except: pass

    # --- VOICE CHAT SERVER THREAD ---
    def voice_server_thread():
        while True:
            try:
                data, addr = voice_sock.recvfrom(2048)
                if len(data) > 36:
                    client_id = data[:36].decode('utf-8', errors='ignore')
                    audio_data = data[36:]
                    c = clients.get(client_id)
                    if c and c.get("room_id") in rooms:
                        r = rooms[c["room_id"]]
                        opp_id = r["p2"] if r["p1"] == client_id else r["p1"]
                        opponent = clients.get(opp_id)
                        if opponent and opponent.get("voice_addr"):
                            voice_sock.sendto(audio_data, opponent["voice_addr"])
            except: pass
    threading.Thread(target=voice_server_thread, daemon=True).start()

    # --- GAME PHYSICS & TIMER LOOP (30 FPS) ---
    def rooms_physics_loop():
        # Buat folder replays jika belum ada
        if not os.path.exists("replays"):
            os.makedirs("replays")

        while True:
            for room_id, r in list(rooms.items()):
                # Inisialisasi file rekaman saat game baru saja dimulai
                if r["status"] == "playing" and "replay_file" not in r:
                    r["replay_file"] = f"replays/match_{room_id}_{int(time.time())}.jsonl"
                    try:
                        with open(r["replay_file"], "w") as f:
                            # Catat metadata map awal agar obstacle tersinkronisasi saat diputar ulang
                            init_data = {"type": "init", "map": r["map"], "usernames": r["usernames"]}
                            f.write(json.dumps(init_data) + "\n")
                    except Exception as e:
                        logging.error(f"Gagal membuat file replay: {e}")

                # Update Timer & Status Game Over
                if r["status"] == "playing" and not r["game_over"]:
                    elapsed = time.time() - r["start_time"]
                    r["timer"] = max(0, int(MATCH_DURATION - elapsed))
                    if r["timer"] <= 0:
                        r["game_over"] = True
                        if r["score"]["1"] > r["score"]["2"]: r["winner"] = 1
                        elif r["score"]["2"] > r["score"]["1"]: r["winner"] = 2
                        else: r["winner"] = 0
                        logging.info(f"Room {room_id} SELESAI. Waktu Habis.")
                    else:
                        stale_player = None
                        for p_id in [r["p1"], r["p2"]]:
                            c = clients.get(p_id)
                            if not c or time.time() - c.get("last_seen", 0) > RECONNECT_TIMEOUT:
                                stale_player = p_id
                                break
                        if stale_player:
                            r["status"] = "waiting_reconnect"
                            r["disconnected"] = stale_player
                            r["disconnect_time"] = time.time()
                            # (Logika penanganan disconnect tetap sama...)

                # Update Fisika Peluru
                if r["status"] == "playing" and not r["game_over"]:
                    new_bullets = []
                    for b in r["bullets"]:
                        rad = math.radians(b["angle"])
                        b["x"] += BULLET_SPEED * math.cos(rad)
                        b["y"] -= BULLET_SPEED * math.sin(rad)
                        
                        if 0 < b["x"] < WIDTH and 0 < b["y"] < HEIGHT:
                            hit_wall = False
                            for obs in r["map"]:
                                if obs["x"] <= b["x"] <= obs["x"]+obs["w"] and obs["y"] <= b["y"] <= obs["y"]+obs["h"]:
                                    hit_wall = True
                                    break
                            if hit_wall: continue
                            
                            target_idx = "2" if b["owner"] == "1" else "1"
                            target = r["state"][target_idx]
                            distance = math.sqrt((b["x"] - target["x"] - 20)**2 + (b["y"] - target["y"] - 20)**2)
                            
                            if distance < 25:
                                target["hp"] -= 20
                                if target["hp"] <= 0:
                                    r["score"][b["owner"]] += 1
                                    target["hp"] = 100 
                                    if target_idx == "1":
                                        target["x"], target["y"] = 100, 300
                                        target["angle"] = 0
                                    else:
                                        target["x"], target["y"] = 700, 300
                                        target["angle"] = 180
                                continue
                            new_bullets.append(b)
                    r["bullets"] = new_bullets

                # --- FITUR UTAMA: AGREGASI STATUS FRAME KE JSON LINES (.jsonl) ---
                if r["status"] == "playing" and "replay_file" in r:
                    try:
                        with open(r["replay_file"], "a") as f:
                            frame_data = {
                                "type": "frame",
                                "state": r["state"],
                                "score": r["score"],
                                "bullets": r["bullets"],
                                "timer": r["timer"],
                                "game_over": r["game_over"]
                            }
                            f.write(json.dumps(frame_data) + "\n")
                    except Exception as e:
                        pass

                # Broadcast Update Jaringan WAJIB TETAP JALAN
                if r["status"] in ["playing", "waiting_reconnect"] or r["game_over"]:
                    update_msg = {
                        "type": "update", "state": r.get("state", {}), "score": r.get("score", {"1":0,"2":0}), "round": r.get("round", 1),
                        "bullets": r.get("bullets", []), "usernames": r.get("usernames", {"1":"P1","2":"P2"}), "map": r.get("map", []),
                        "game_over": r["game_over"], "winner": r["winner"], "timer": r.get("timer", MATCH_DURATION)
                    }
                    for p_id in [r["p1"], r["p2"]]:
                        if p_id in clients: send_to(clients[p_id]["addr"], update_msg)
                    for spec_id in r["spectators"]:
                        if spec_id in clients: send_to(clients[spec_id]["addr"], update_msg)
            time.sleep(1/30)
    threading.Thread(target=rooms_physics_loop, daemon=True).start()

    # --- COMMAND RECEIVER LOOP ---
    while True:
        try:
            data, addr = sock.recvfrom(2048)
            try: msg = json.loads(data.decode('utf-8'))
            except: continue
                
            msg_type = msg.get("type")
            if msg_type == "ping": send_to(addr, {"type": "pong", "time": msg.get("time", 0)}); continue
                
            client_id = msg.get("client_id")
            if not client_id: continue
            if client_id not in clients:
                username = msg.get("username", "Guest")
                clients[client_id] = {"addr": addr, "room_id": None, "player_idx": None, "username": username, "voice_addr": None, "connected": True, "last_seen": time.time()}
            else:
                if clients[client_id]["addr"] != addr:
                    clients[client_id]["addr"] = addr
                clients[client_id]["last_seen"] = time.time()
                clients[client_id]["connected"] = True
                if msg_type == "join":
                    clients[client_id]["username"] = msg.get("username", clients[client_id].get("username", "Guest"))

            if msg_type == "join":
                username = msg.get("username", "Guest")
                existing_client = clients.get(client_id)
                if existing_client and existing_client.get("room_id") in rooms:
                    r = rooms[existing_client["room_id"]]
                    if r["status"] == "waiting_reconnect" and r.get("disconnected") == client_id:
                        existing_client.update({"addr": addr, "username": username, "connected": True, "last_seen": time.time()})
                        r["status"] = "playing"
                        r["disconnected"] = None
                        r["disconnect_time"] = None
                        logging.info(f"Player reconnected: {username} ({client_id}) in room {existing_client['room_id']}")
                        other_id = r["p1"] if client_id == r["p2"] else r["p2"]
                        if other_id in clients:
                            send_to(clients[other_id]["addr"], {"type": "opponent_reconnected", "msg": "Opponent reconnected. Game resumes."})
                        send_to(addr, {
                            "type": "reconnect_success", "player_idx": existing_client["player_idx"], "map": r["map"],
                            "round": r["round"], "score": r["score"], "state": r["state"], "game_over": r["game_over"],
                            "winner": r["winner"], "timer": r["timer"]
                        })
                        continue
                send_to(addr, {"type": "join_ack"})
                
            elif msg_type == "create_room":
                while True:
                    room_id = str(random.randint(1000, 9999))
                    if room_id not in rooms: break
                clients[client_id].update({"room_id": room_id, "player_idx": 1})
                rooms[room_id] = {
                    "p1": client_id, "p2": None, "spectators": [], "is_private": msg.get("is_private", False),
                    "password": msg.get("password", ""), "status": "waiting", "host_username": clients[client_id]["username"],
                    "bullets": [], "timer": MATCH_DURATION, "disconnected": None, "disconnect_time": None, "game_over": False, "winner": None
                }
                logging.info(f"Room created: {room_id} by {clients[client_id]['username']} ({client_id})")
                send_to(addr, {"type": "room_created", "room_id": room_id, "is_private": msg.get("is_private", False)})
                
            elif msg_type == "get_public_rooms":
                pub_rooms = [{"room_id": rid, "host": r["host_username"], "status": r["status"]} for rid, r in rooms.items() if not r["is_private"]]
                send_to(addr, {"type": "public_rooms_list", "rooms": pub_rooms})
                
            elif msg_type == "join_room":
                room_id = str(msg.get("room_id", ""))
                if room_id not in rooms:
                    send_to(addr, {"type": "join_error", "msg": "Room tidak ditemukan"}); continue
                r = rooms[room_id]
                
                if msg.get("as_spectator", False):
                    if client_id not in r["spectators"]:
                        r["spectators"].append(client_id)
                    clients[client_id].update({"room_id": room_id, "player_idx": "spectator"})
                    
                    if r["status"] == "playing":
                        spec_msg = {
                            "type": "match_found", "player_idx": "spectator", "map": r["map"], "round": r.get("round", 1),
                            "score": r["score"], "state": r["state"], "bullets": r["bullets"], "timer": r["timer"],
                            "game_over": r["game_over"], "winner": r["winner"], "usernames": r["usernames"]
                        }
                    else:
                        spec_msg = {"type": "spectator_waiting", "room_id": room_id, "msg": "Menunggu match dimulai..."}
                    send_to(addr, spec_msg)
                    continue
                    
                if r.get("p2") is not None:
                    send_to(addr, {"type": "join_error", "msg": "Room sudah penuh"})
                    continue

                r["p2"] = client_id
                clients[client_id].update({"room_id": room_id, "player_idx": 2})
                logging.info(f"Player joined room {room_id}: {clients[client_id]['username']} ({client_id}) as P2")
                
                map_obstacles = [{"x": random.randint(180, 580), "y": random.randint(80, 420), "w": random.randint(50, 100), "h": random.randint(50, 100)} for _ in range(6)]
                r.update({
                    "map": map_obstacles, "round": 1, "score": {"1": 0, "2": 0},
                    "usernames": {"1": clients[r["p1"]]["username"], "2": clients[client_id]["username"]},
                    "game_over": False, "winner": None,
                    "state": {"1": {"x": 100, "y": 300, "angle": 0, "hp": 100}, "2": {"x": 700, "y": 300, "angle": 180, "hp": 100}},
                    "status": "playing", "start_time": time.time()
                })
                
                match_found_msg = {
                    "type": "match_found", "map": r["map"], "round": r["round"], "score": r["score"],
                    "state": r["state"], "bullets": r["bullets"], "timer": r["timer"],
                    "game_over": r["game_over"], "winner": r["winner"], "usernames": r["usernames"]
                }
                
                for p_idx, p_cid in [(1, r["p1"]), (2, r["p2"])]:
                    match_found_msg["player_idx"] = p_idx
                    send_to(clients[p_cid]["addr"], match_found_msg)
                
                for spec_id in r["spectators"]:
                    if spec_id in clients:
                        match_found_msg["player_idx"] = "spectator"
                        send_to(clients[spec_id]["addr"], match_found_msg)
                logging.info(f"Match started in room {room_id}")

            elif msg_type == "action":
                c = clients.get(client_id)
                if c and c["room_id"] in rooms:
                    r = rooms[c["room_id"]]
                    pidx = str(c["player_idx"])
                    if pidx == "spectator" or r["game_over"]: continue
                    
                    p_tank = r["state"][pidx]
                    dx, dy = 0, 0
                    keys = msg.get("keys", [])
                    
                    if "MOVE_UP" in keys: dy -= TANK_SPEED
                    if "MOVE_DOWN" in keys: dy += TANK_SPEED
                    if "MOVE_LEFT" in keys: dx -= TANK_SPEED
                    if "MOVE_RIGHT" in keys: dx += TANK_SPEED
                    if "ROT_LEFT" in keys: p_tank["angle"] = (p_tank["angle"] + 5) % 360
                    if "ROT_RIGHT" in keys: p_tank["angle"] = (p_tank["angle"] - 5) % 360
                    
                    if dx != 0 or dy != 0:
                        future_x = p_tank["x"] + dx
                        future_y = p_tank["y"] + dy
                        collided = False
                        for obs in r["map"]:
                            if (obs["x"] - 35 <= future_x <= obs["x"] + obs["w"]) and (obs["y"] - 35 <= future_y <= obs["y"] + obs["h"]):
                                collided = True
                                break
                        if not collided:
                            p_tank["x"] = max(10, min(WIDTH - 50, future_x))
                            p_tank["y"] = max(10, min(HEIGHT - 50, future_y))

                    if msg.get("shoot") and len(r["bullets"]) < 10:
                        r["bullets"].append({"owner": pidx, "x": p_tank["x"] + 20, "y": p_tank["y"] + 20, "angle": p_tank["angle"]})

            elif msg_type == "leave_room":
                if client_id in clients and clients[client_id]["room_id"] in rooms:
                    room_id = clients[client_id]["room_id"]
                    r = rooms[room_id]
                    if clients[client_id]["player_idx"] == "spectator":
                        if client_id in r["spectators"]: r["spectators"].remove(client_id)
                        clients[client_id]["room_id"] = None
                    elif r["status"] == "playing":
                        if r["status"] != "waiting_reconnect":
                            r["disconnected"] = client_id
                            r["disconnect_time"] = time.time()
                            r["status"] = "waiting_reconnect"
                            clients[client_id]["connected"] = False
                            other_id = r["p1"] if client_id == r["p2"] else r["p2"]
                            if other_id in clients:
                                send_to(clients[other_id]["addr"], {"type": "opponent_disconnected", "msg": "Opponent disconnected. Waiting for reconnect..."})
                            for spec_id in r["spectators"]:
                                if spec_id in clients:
                                    send_to(clients[spec_id]["addr"], {"type": "opponent_disconnected", "msg": "A player disconnected. Waiting for reconnect..."})
                    else:
                        del rooms[room_id]
                        clients[client_id]["room_id"] = None
        except: pass

if __name__ == "__main__":
    main()
