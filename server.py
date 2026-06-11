import socket
import threading
import json
import time
import random
import math
import logging
import os

HOST = '127.0.0.1'
PORT = 5555

WIDTH, HEIGHT = 800, 600
TANK_SPEED = 10
BULLET_SPEED = 25

# Fitur Wajib: Logging Aktivitas Player
logging.basicConfig(filename='server_activity.log', level=logging.INFO, 
                    format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

class TankArenaServer:
    def __init__(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((HOST, PORT))
        self.server.listen()
        
        self.rooms = {} 
        self.waiting_player = None 
        print(f"[*] Server Tank Arena berjalan di {HOST}:{PORT}")
        logging.info("Server started.")

    def generate_obstacles(self, seed):
        """Server men-generate rintangan yang sama dengan klien untuk Collision"""
        random.seed(seed)
        obstacles = []
        for _ in range(8):
            x = random.randint(150, WIDTH - 200)
            y = random.randint(100, HEIGHT - 150)
            obstacles.append({"x": x, "y": y, "w": 60, "h": 60})
        return obstacles

    def check_collision(self, rect1, obstacles):
        """Fungsi AABB Collision dasar tanpa perlu library Pygame di Server"""
        for obs in obstacles:
            if (rect1["x"] < obs["x"] + obs["w"] and
                rect1["x"] + rect1["w"] > obs["x"] and
                rect1["y"] < obs["y"] + obs["h"] and
                rect1["y"] + rect1["h"] > obs["y"]):
                return True
        return False

    def create_room(self, p1_conn, p1_addr):
        room_id = f"ROOM_{int(time.time())}"
        map_seed = random.randint(1, 100000)
        self.rooms[room_id] = {
            "room_id": room_id, "status": "WAITING", "map_seed": map_seed,
            "obstacles": self.generate_obstacles(map_seed), # Simpan posisi obstacle
            "timer": 60, "start_time": None,
            "players": {"P1": {"conn": p1_conn, "addr": p1_addr, "x": 100, "y": 300, "angle": 0, "score": 0, "hp": 100, "connected": True}},
            "spectators": [], "bullets": [], "replay_data": [] # Bonus: Match Replay
        }
        return room_id

    def join_room(self, room_id, p2_conn, p2_addr):
        room = self.rooms[room_id]
        room["players"]["P2"] = {"conn": p2_conn, "addr": p2_addr, "x": 700, "y": 300, "angle": 180, "score": 0, "hp": 100, "connected": True}
        
        p2_conn.send((json.dumps({"type": "INIT", "role": "P2", "room_id": room_id, "seed": room["map_seed"]}) + "\n").encode())
        p1_conn = room["players"]["P1"]["conn"]
        p1_conn.send((json.dumps({"type": "INIT", "role": "P1", "room_id": room_id, "seed": room["map_seed"]}) + "\n").encode())
        
        time.sleep(0.2)
        room["status"] = "PLAYING"
        room["start_time"] = time.time()
        logging.info(f"Room {room_id} started playing.")
        threading.Thread(target=self.room_game_loop, args=(room_id,), daemon=True).start()

    def save_leaderboard_and_replay(self, room):
        """Bonus: Ranking System & Match Replay"""
        # Save Leaderboard
        scores = {}
        if os.path.exists('leaderboard.json'):
            with open('leaderboard.json', 'r') as f:
                scores = json.load(f)
        
        scores[f"Player 1 ({room['room_id']})"] = room["players"]["P1"]["score"]
        if "P2" in room["players"]:
            scores[f"Player 2 ({room['room_id']})"] = room["players"]["P2"]["score"]
            
        with open('leaderboard.json', 'w') as f:
            json.dump(scores, f)

        # Save Match Replay
        with open(f"replay_{room['room_id']}.json", 'w') as f:
            json.dump(room["replay_data"], f)
        logging.info(f"Match replay and leaderboard updated for {room['room_id']}")

    def handle_client(self, conn, addr):
        logging.info(f"Connection from {addr}")
        player_room_id = None
        player_role = None

        try:
            active_room_id = None
            for r_id, r_data in self.rooms.items():
                if r_data["status"] == "PLAYING":
                    active_room_id = r_id
                    break
            
            if active_room_id:
                player_room_id = active_room_id
                player_role = "SPECTATOR"
                self.rooms[player_room_id]["spectators"].append({"conn": conn, "addr": addr, "connected": True})
                conn.send((json.dumps({"type": "INIT", "role": player_role, "room_id": player_room_id, "seed": self.rooms[player_room_id]["map_seed"]}) + "\n").encode())
            elif not self.waiting_player:
                player_room_id = self.create_room(conn, addr)
                player_role = "P1"
                self.waiting_player = player_room_id
                conn.send((json.dumps({"type": "INIT", "role": player_role, "room_id": player_room_id, "seed": self.rooms[player_room_id]["map_seed"]}) + "\n").encode())
            else:
                player_room_id = self.waiting_player
                player_role = "P2"
                self.waiting_player = None
                self.join_room(player_room_id, conn, addr)
        except Exception as e:
            conn.close()
            return

        while True:
            try:
                data = conn.recv(1024).decode()
                if not data: break
                messages = data.strip().split('\n')
                for message in messages:
                    if not message: continue
                    
                    # Fitur Wajib: Anti-invalid packet sederhana
                    try:
                        msg = json.loads(message)
                        if "type" not in msg: continue
                    except json.JSONDecodeError:
                        logging.warning(f"Malformed packet from {addr}")
                        continue
                    
                    if msg["type"] == "PING":
                        conn.send((json.dumps({"type": "PONG", "timestamp": msg["timestamp"]}) + "\n").encode())
                        continue
                    
                    # Bonus: Simple Text Communication (Voice alternative for TCP stability)
                    if msg["type"] == "CHAT":
                        self.broadcast_chat(player_room_id, f"{player_role}: {msg['text']}")
                        continue

                    if player_role == "SPECTATOR": continue
                    
                    room = self.rooms.get(player_room_id)
                    if room and msg["type"] == "INPUT" and room["status"] == "PLAYING":
                        p_data = room["players"][player_role]
                        
                        # Simpan posisi sementara untuk mengecek collision
                        new_x, new_y = p_data["x"], p_data["y"]
                        
                        if "MOVE_UP" in msg["keys"]: new_y = max(20, p_data["y"] - TANK_SPEED)
                        if "MOVE_DOWN" in msg["keys"]: new_y = min(HEIGHT-20, p_data["y"] + TANK_SPEED)
                        if "MOVE_LEFT" in msg["keys"]: new_x = max(20, p_data["x"] - TANK_SPEED)
                        if "MOVE_RIGHT" in msg["keys"]: new_x = min(WIDTH-20, p_data["x"] + TANK_SPEED)
                        
                        # Validasi Tembus Rintangan (Tank vs Obstacle)
                        tank_rect = {"x": new_x - 20, "y": new_y - 20, "w": 40, "h": 40}
                        if not self.check_collision(tank_rect, room["obstacles"]):
                            p_data["x"], p_data["y"] = new_x, new_y

                        if "ROT_LEFT" in msg["keys"]: p_data["angle"] = (p_data["angle"] + 5) % 360
                        if "ROT_RIGHT" in msg["keys"]: p_data["angle"] = (p_data["angle"] - 5) % 360
                        
                        if msg.get("shoot") and len(room["bullets"]) < 10:
                            room["bullets"].append({"owner": player_role, "x": p_data["x"], "y": p_data["y"], "angle": p_data["angle"]})
                            logging.info(f"{player_role} fired a bullet.")
            except:
                break

        if player_room_id in self.rooms:
            room = self.rooms[player_room_id]
            if player_role in room["players"]: room["players"][player_role]["connected"] = False
            logging.info(f"{player_role} disconnected from {player_room_id}")
        conn.close()

    def broadcast_chat(self, room_id, text):
        room = self.rooms.get(room_id)
        if room:
            data = (json.dumps({"type": "CHAT_MSG", "text": text}) + "\n").encode()
            for p in room["players"].values():
                if p["connected"]: p["conn"].send(data)

    def room_game_loop(self, room_id):
        while room_id in self.rooms:
            room = self.rooms[room_id]
            if room["status"] == "PLAYING":
                elapsed = time.time() - room["start_time"]
                room["timer"] = max(0, int(60 - elapsed))
                if room["timer"] <= 0: 
                    room["status"] = "ENDED"
                    self.save_leaderboard_and_replay(room)

                new_bullets = []
                for b in room["bullets"]:
                    rad = math.radians(b["angle"])
                    b["x"] += BULLET_SPEED * math.cos(rad)
                    b["y"] -= BULLET_SPEED * math.sin(rad)
                    
                    # Validasi Peluru Keluar Layar
                    if not (0 < b["x"] < WIDTH and 0 < b["y"] < HEIGHT):
                        continue

                    # Validasi Tembus Rintangan (Bullet vs Obstacle)
                    bullet_rect = {"x": b["x"] - 5, "y": b["y"] - 5, "w": 10, "h": 10}
                    if self.check_collision(bullet_rect, room["obstacles"]):
                        continue # Peluru hancur kena rintangan

                    # Validasi Kena Tank Musuh
                    hit = False
                    for target_role, target in room["players"].items():
                        if target_role != b["owner"] and target["connected"]:
                            distance = math.sqrt((b["x"] - target["x"])**2 + (b["y"] - target["y"])**2)
                            if distance < 30: 
                                target["hp"] -= 20
                                hit = True
                                logging.info(f"{b['owner']} hit {target_role}!")
                                if target["hp"] <= 0:
                                    room["players"][b["owner"]]["score"] += 1
                                    target["hp"] = 100
                                    target["x"], target["y"] = (100, 300) if target_role == "P1" else (700, 300)
                    if not hit:
                        new_bullets.append(b)
                        
                room["bullets"] = new_bullets
                self.broadcast_state(room)
            time.sleep(1/30)

    def broadcast_state(self, room):
        state_to_send = {
            "type": "UPDATE", "status": room["status"], "timer": room["timer"],
            "bullets": [{ "x": b["x"], "y": b["y"] } for b in room["bullets"]],
            "players": {role: {"x": p["x"], "y": p["y"], "angle": p["angle"], "score": p["score"], "hp": p["hp"], "connected": p["connected"]} for role, p in room["players"].items()}
        }
        # Rekam state untuk replay
        if room["status"] == "PLAYING":
            room["replay_data"].append(state_to_send)

        data_bytes = (json.dumps(state_to_send) + "\n").encode()
        for role, p in room["players"].items():
            if p["connected"]:
                try: p["conn"].send(data_bytes)
                except: p["connected"] = False
        for spec in room["spectators"]:
            try: spec["conn"].send(data_bytes)
            except: pass

    def start(self):
        while True:
            # Menerima koneksi masuk dari client
            conn, addr = self.server.accept()
            # Membuat thread baru untuk setiap client yang terhubung
            threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    server = TankArenaServer()
    server.start()
