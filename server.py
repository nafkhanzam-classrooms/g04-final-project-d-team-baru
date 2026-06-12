import socket
import json
import uuid
import random
import os
import time
import logging
from datetime import datetime
import threading

# Setup Logging
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

LEADERBOARD_FILE = "leaderboard.json"

def load_leaderboard():
    if os.path.exists(LEADERBOARD_FILE):
        try:
            with open(LEADERBOARD_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_leaderboard(data):
    with open(LEADERBOARD_FILE, "w") as f:
        json.dump(data, f)


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    
    VOICE_PORT = PORT + 1
    voice_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    voice_sock.bind((HOST, VOICE_PORT))
    
    logging.info(f"=== UDP Game Server Started on {HOST}:{PORT} ===")
    logging.info(f"=== UDP Voice Server Started on {HOST}:{VOICE_PORT} ===")
    
    os.makedirs("replays", exist_ok=True)
    
    # State management
    leaderboard = load_leaderboard()
    clients = {} # client_id -> {"addr": (ip, port), "room_id": str, "player_idx": 1 or 2, "username": str, "voice_addr": None}
    rooms = {} # room_id -> {"p1": client_id, "p2": client_id, "is_private": bool, ...}
    
    def send_to(addr, data_dict):
        try:
            sock.sendto(json.dumps(data_dict).encode('utf-8'), addr)
        except Exception as e:
            logging.error(f"Failed sending to {addr}: {e}")

    def voice_server_thread():
        while True:
            try:
                data, addr = voice_sock.recvfrom(2048)
                if len(data) > 36:
                    client_id = data[:36].decode('utf-8', errors='ignore')
                    audio_data = data[36:]
                    
                    c = clients.get(client_id)
                    if c:
                        if c.get("voice_addr") != addr:
                            c["voice_addr"] = addr
                        
                        room_id = c.get("room_id")
                        if room_id and room_id in rooms:
                            r = rooms[room_id]
                            opponent_id = r["p2"] if r["p1"] == client_id else r["p1"]
                            opponent = clients.get(opponent_id)
                            if opponent and opponent.get("voice_addr"):
                                try:
                                    voice_sock.sendto(audio_data, opponent["voice_addr"])
                                except Exception:
                                    pass
            except Exception as e:
                logging.error(f"Voice server exception: {e}")

    threading.Thread(target=voice_server_thread, daemon=True).start()

    while True:
        try:
            data, addr = sock.recvfrom(1024)
            
            # --- ANTI-INVALID PACKET SEDERHANA ---
            try:
                msg = json.loads(data.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                logging.warning(f"Invalid packet format received from {addr}")
                continue
                
            msg_type = msg.get("type")
            if not msg_type:
                logging.warning(f"Packet without 'type' from {addr}")
                continue
            
            # --- PING / PONG (Latency Indicator) ---
            if msg_type == "ping":
                send_to(addr, {"type": "pong", "time": msg.get("time", 0)})
                continue
                
            client_id = msg.get("client_id")
            if not client_id:
                logging.warning(f"Packet without 'client_id' from {addr}")
                continue
                
            # --- RECONNECT HANDLING ---
            # Jika alamat ip/port berbeda dari yang tersimpan, namun client_id sama, update alamatnya
            if client_id in clients:
                if clients[client_id]["addr"] != addr:
                    logging.info(f"Player {client_id[:8]} reconnected from new address {addr}")
                    clients[client_id]["addr"] = addr
            
            if msg_type == "join":
                username = msg.get("username", "Guest")
                if client_id not in clients:
                    clients[client_id] = {"addr": addr, "room_id": None, "player_idx": None, "username": username, "voice_addr": None}
                    logging.info(f"Player {client_id[:8]} ({username}) connected to lobby.")
                else:
                    # Update username jika berubah
                    clients[client_id]["username"] = username
                    
            elif msg_type == "get_leaderboard":
                sorted_lb = sorted(leaderboard.items(), key=lambda item: item[1], reverse=True)[:5]
                send_to(addr, {"type": "leaderboard_data", "leaderboard": sorted_lb})
                continue

            elif msg_type == "create_room":
                is_private = msg.get("is_private", False)
                password = msg.get("password", "")
                
                # Generate unique 4 digit room id
                while True:
                    room_id = str(random.randint(1000, 9999))
                    if room_id not in rooms:
                        break
                        
                clients[client_id]["room_id"] = room_id
                clients[client_id]["player_idx"] = 1
                
                rooms[room_id] = {
                    "p1": client_id,
                    "p2": None,
                    "spectators": [],
                    "is_private": is_private,
                    "password": password,
                    "status": "waiting",
                    "host_username": clients[client_id]["username"]
                }
                
                send_to(addr, {
                    "type": "room_created",
                    "room_id": room_id,
                    "is_private": is_private
                })
                logging.info(f"Room {room_id} created by {clients[client_id]['username']} (Private: {is_private})")
                
            elif msg_type == "get_public_rooms":
                pub_rooms = []
                for rid, r in rooms.items():
                    if not r["is_private"] and r["status"] == "waiting":
                        pub_rooms.append({"room_id": rid, "host": r["host_username"]})
                send_to(addr, {"type": "public_rooms_list", "rooms": pub_rooms})
                
            elif msg_type == "join_room":
                room_id = str(msg.get("room_id", ""))
                password = msg.get("password", "")
                as_spectator = msg.get("as_spectator", False)
                
                if room_id not in rooms:
                    send_to(addr, {"type": "join_error", "msg": "Room not found"})
                    continue
                    
                r = rooms[room_id]
                
                if r["is_private"] and r["password"] != password:
                    send_to(addr, {"type": "join_error", "msg": "Wrong password"})
                    continue
                    
                if as_spectator:
                    r["spectators"].append(client_id)
                    clients[client_id]["room_id"] = room_id
                    clients[client_id]["player_idx"] = "spectator"
                    logging.info(f"Player {client_id[:8]} joined Room {room_id} as Spectator.")
                    
                    if r["status"] == "playing":
                        send_to(addr, {
                            "type": "match_found", 
                            "player_idx": "spectator",
                            "map": r["map"],
                            "round": r["round"],
                            "score": r["score"],
                            "state": r["state"]
                        })
                    continue
                
                if r["status"] != "waiting":
                    send_to(addr, {"type": "join_error", "msg": "Room is full or already playing"})
                    continue
                    
                # Match Found!
                r["p2"] = client_id
                r["status"] = "playing"
                
                clients[client_id]["room_id"] = room_id
                clients[client_id]["player_idx"] = 2
                
                p1_id = r["p1"]
                p2_id = client_id
                
                # Generate random map
                map_obstacles = []
                for _ in range(random.randint(5, 8)):
                    ox = random.randint(200, 550)
                    oy = random.randint(50, 450)
                    ow = random.randint(30, 100)
                    oh = random.randint(30, 100)
                    map_obstacles.append({"x": ox, "y": oy, "w": ow, "h": oh})
                    
                r.update({
                    "map": map_obstacles,
                    "round": 1,
                    "score": {"1": 0, "2": 0},
                    "usernames": {"1": clients[p1_id]["username"], "2": clients[p2_id]["username"]},
                    "game_over": False,
                    "winner": None,
                    "state": {
                        "1": {"x": 100, "y": 300, "angle": "RIGHT", "bullets": [], "hp": 100},
                        "2": {"x": 700, "y": 300, "angle": "LEFT", "bullets": [], "hp": 100}
                    }
                })
                
                r["replay_file"] = f"replays/match_{room_id}_{int(time.time())}.jsonl"
                try:
                    with open(r["replay_file"], "w") as f:
                        init_data = {
                            "type": "init",
                            "map": map_obstacles,
                            "usernames": {"1": clients[p1_id]["username"], "2": clients[p2_id]["username"]},
                            "time": time.time()
                        }
                        f.write(json.dumps(init_data) + "\n")
                except Exception as e:
                    logging.error(f"Failed to create replay file: {e}")
                    
                logging.info(f"Room {room_id} Started! Player {p1_id[:8]} vs Player {p2_id[:8]}")
                
                for p_idx, p_cid in [(1, p1_id), (2, p2_id)]:
                    c = clients[p_cid]
                    send_to(c["addr"], {
                        "type": "match_found", 
                        "player_idx": c["player_idx"],
                        "map": r["map"],
                        "round": r["round"],
                        "score": r["score"]
                    })
                    
            # --- GAME STATE SYNCHRONIZATION ---
            elif msg_type == "state":
                c = clients.get(client_id)
                if c and c["room_id"] is not None:
                    if c["player_idx"] == "spectator":
                        continue
                    
                    room_id = c["room_id"]
                    pidx = str(c["player_idx"])
                    
                    # Update server state
                    if not rooms[room_id]["game_over"]:
                        if "x" in msg and "y" in msg:
                            rooms[room_id]["state"][pidx]["x"] = msg["x"]
                            rooms[room_id]["state"][pidx]["y"] = msg["y"]
                        if "angle" in msg:
                            rooms[room_id]["state"][pidx]["angle"] = msg["angle"]
                        if "bullets" in msg:
                            rooms[room_id]["state"][pidx]["bullets"] = msg["bullets"]
                    
                    # Broadcast latest state ke kedua player di room
                    r = rooms[room_id]
                    p1_addr = clients[r["p1"]]["addr"]
                    p2_addr = clients[r["p2"]]["addr"]
                    
                    update_msg = {
                        "type": "update",
                        "state": r["state"],
                        "score": r["score"],
                        "round": r["round"],
                        "usernames": r["usernames"],
                        "game_over": r["game_over"],
                        "winner": r["winner"]
                    }
                    if r["game_over"]:
                        # Sort top 5
                        sorted_lb = sorted(leaderboard.items(), key=lambda item: item[1], reverse=True)[:5]
                        update_msg["leaderboard"] = sorted_lb
                        
                    if "replay_file" in r:
                        try:
                            with open(r["replay_file"], "a") as f:
                                frame_data = {
                                    "type": "frame",
                                    "state": r["state"],
                                    "score": r["score"],
                                    "round": r["round"],
                                    "game_over": r["game_over"],
                                    "winner": r["winner"],
                                    "time": time.time()
                                }
                                f.write(json.dumps(frame_data) + "\n")
                        except Exception:
                            pass
                        
                    # Mengirimkan update secara independen
                    send_to(p1_addr, update_msg)
                    send_to(p2_addr, update_msg)
                    for spec_id in r["spectators"]:
                        if spec_id in clients:
                            send_to(clients[spec_id]["addr"], update_msg)
                    
            # --- HIT DETECTION ---
            elif msg_type == "hit":
                c = clients.get(client_id)
                if c and c["room_id"] is not None:
                    if c["player_idx"] == "spectator":
                        continue
                        
                    room_id = c["room_id"]
                    r = rooms[room_id]
                    
                    if r["game_over"]:
                        continue
                        
                    target_idx = str(msg.get("target"))
                    shooter_idx = str(c["player_idx"])
                    
                    # Kurangi HP
                    r["state"][target_idx]["hp"] -= 20
                    
                    if r["state"][target_idx]["hp"] <= 0:
                        logging.info(f"Player {shooter_idx} killed Player {target_idx} in Room {room_id}")
                        r["score"][shooter_idx] += 1
                        
                        # Cek menang game (Best of 5 -> butuh 3 poin)
                        if r["score"][shooter_idx] >= 3:
                            r["game_over"] = True
                            r["winner"] = int(shooter_idx)
                            logging.info(f"Room {room_id} GAME OVER. Winner: {shooter_idx}")
                            
                            # Update Leaderboard
                            winner_uname = r["usernames"][shooter_idx]
                            leaderboard[winner_uname] = leaderboard.get(winner_uname, 0) + 1
                            save_leaderboard(leaderboard)
                        else:
                            # Lanjut ke ronde berikutnya
                            r["round"] += 1
                            r["state"]["1"]["hp"] = 100
                            r["state"]["2"]["hp"] = 100
                            r["state"]["1"]["x"] = 100
                            r["state"]["1"]["y"] = 300
                            r["state"]["2"]["x"] = 700
                            r["state"]["2"]["y"] = 300
                            
                            # Generate map baru
                            map_obstacles = []
                            for _ in range(random.randint(5, 8)):
                                ox = random.randint(200, 550)
                                oy = random.randint(50, 450)
                                ow = random.randint(30, 100)
                                oh = random.randint(30, 100)
                                map_obstacles.append({"x": ox, "y": oy, "w": ow, "h": oh})
                            r["map"] = map_obstacles
                            
                            logging.info(f"Room {room_id} advances to Round {r['round']}")
                            
                            if "replay_file" in r:
                                try:
                                    with open(r["replay_file"], "a") as f:
                                        reset_data = {
                                            "type": "round_reset",
                                            "map": map_obstacles,
                                            "round": r["round"],
                                            "time": time.time()
                                        }
                                        f.write(json.dumps(reset_data) + "\n")
                                except Exception:
                                    pass
                            
                            # Kirim sinyal round_reset
                            reset_msg = {
                                "type": "round_reset",
                                "round": r["round"],
                                "score": r["score"],
                                "map": map_obstacles,
                                "state": r["state"]
                            }
                            send_to(clients[r["p1"]]["addr"], reset_msg)
                            send_to(clients[r["p2"]]["addr"], reset_msg)
                            for spec_id in r["spectators"]:
                                if spec_id in clients:
                                    send_to(clients[spec_id]["addr"], reset_msg)
                    
        except Exception as e:
            logging.error(f"Server exception: {e}")

if __name__ == "__main__":
    main()
