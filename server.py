import socket
import threading
import json
import time
import random
import math

HOST = '127.0.0.1'
PORT = 5555  # Kita pakai port baru 5555 agar bersih

WIDTH, HEIGHT = 800, 600
TANK_SPEED = 5
BULLET_SPEED = 8

class TankArenaServer:
    def __init__(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((HOST, PORT))
        self.server.listen()
        
        self.rooms = {} 
        self.waiting_player = None 
        print(f"[*] Server Tank Arena berjalan di {HOST}:{PORT}")

    def create_room(self, p1_conn, p1_addr):
        room_id = f"ROOM_{int(time.time())}"
        map_seed = random.randint(1, 100000)
        self.rooms[room_id] = {
            "room_id": room_id, "status": "WAITING", "map_seed": map_seed,
            "timer": 60, "start_time": None,
            "players": {"P1": {"conn": p1_conn, "addr": p1_addr, "x": 100, "y": 300, "angle": 0, "score": 0, "hp": 100, "connected": True}},
            "spectators": [], "bullets": []
        }
        return room_id

    def join_room(self, room_id, p2_conn, p2_addr):
        room = self.rooms[room_id]
        room["players"]["P2"] = {"conn": p2_conn, "addr": p2_addr, "x": 700, "y": 300, "angle": 180, "score": 0, "hp": 100, "connected": True}
        
        # Kirim data INIT
        p2_conn.send((json.dumps({"type": "INIT", "role": "P2", "room_id": room_id, "seed": room["map_seed"]}) + "\n").encode())
        p1_conn = room["players"]["P1"]["conn"]
        p1_conn.send((json.dumps({"type": "INIT", "role": "P1", "room_id": room_id, "seed": room["map_seed"]}) + "\n").encode())
        
        time.sleep(0.2) # Jeda waktu agar client tidak crash menerima paket beruntun
        room["status"] = "PLAYING"
        room["start_time"] = time.time()
        threading.Thread(target=self.room_game_loop, args=(room_id,), daemon=True).start()

    def handle_client(self, conn, addr):
        print(f"[+] Koneksi masuk dari {addr}")
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
                print(f"[+ BONUS] {addr} bergabung sebagai SPECTATOR.")
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
                    msg = json.loads(message)
                    
                    if msg["type"] == "PING":
                        conn.send((json.dumps({"type": "PONG", "timestamp": msg["timestamp"]}) + "\n").encode())
                        continue
                    
                    if player_role == "SPECTATOR": continue
                    
                    room = self.rooms.get(player_room_id)
                    if room and msg["type"] == "INPUT" and room["status"] == "PLAYING":
                        p_data = room["players"][player_role]
                        if "MOVE_UP" in msg["keys"]: p_data["y"] = max(50, p_data["y"] - TANK_SPEED)
                        if "MOVE_DOWN" in msg["keys"]: p_data["y"] = min(HEIGHT-50, p_data["y"] + TANK_SPEED)
                        if "MOVE_LEFT" in msg["keys"]: p_data["x"] = max(50, p_data["x"] - TANK_SPEED)
                        if "MOVE_RIGHT" in msg["keys"]: p_data["x"] = min(WIDTH-50, p_data["x"] + TANK_SPEED)
                        if "ROT_LEFT" in msg["keys"]: p_data["angle"] = (p_data["angle"] + 5) % 360
                        if "ROT_RIGHT" in msg["keys"]: p_data["angle"] = (p_data["angle"] - 5) % 360
                        if msg.get("shoot") and len(room["bullets"]) < 10:
                            room["bullets"].append({"owner": player_role, "x": p_data["x"], "y": p_data["y"], "angle": p_data["angle"]})
            except:
                break

        if player_room_id in self.rooms:
            room = self.rooms[player_room_id]
            if player_role in room["players"]: room["players"][player_role]["connected"] = False
            if not room["players"]["P1"]["connected"] and ("P2" not in room["players"] or not room["players"]["P2"]["connected"]):
                del self.rooms[player_room_id]
                if self.waiting_player == player_room_id: self.waiting_player = None
        conn.close()

    def room_game_loop(self, room_id):
        while room_id in self.rooms:
            room = self.rooms[room_id]
            if room["status"] == "PLAYING":
                elapsed = time.time() - room["start_time"]
                room["timer"] = max(0, int(60 - elapsed))
                if room["timer"] <= 0: room["status"] = "ENDED"

                new_bullets = []
                for b in room["bullets"]:
                    rad = math.radians(b["angle"])
                    b["x"] += BULLET_SPEED * math.cos(rad)
                    b["y"] -= BULLET_SPEED * math.sin(rad)
                    if 0 < b["x"] < WIDTH and 0 < b["y"] < HEIGHT:
                        target_role = "P2" if b["owner"] == "P1" else "P1"
                        target = room["players"].get(target_role)
                        if target:
                            distance = math.sqrt((b["x"] - target["x"])**2 + (b["y"] - target["y"])**2)
                            if distance < 30: 
                                target["hp"] -= 20
                                if target["hp"] <= 0:
                                    room["players"][b["owner"]]["score"] += 1
                                    target["hp"] = 100
                                    target["x"], target["y"] = (100, 300) if target_role == "P1" else (700, 300)
                                continue 
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
            conn, addr = self.server.accept()
            threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    server = TankArenaServer()
    server.start()