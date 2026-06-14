[![Review Assignment Due Date](https://classroom.github.com/assets/deadline-readme-button-22041afd0340ce965d47ae6ef1cefeee28c7c493a6346c4f15d667ab976d596c.svg)](https://classroom.github.com/a/4SHtB1vz)

| Nama | NRP |
| :--- | :--- |
| Aziz Adi Pramana | 5025241195 |
| Afsal Murtaza | 5025241190 |
| Khairan Cherokee Musthofa | 5025241215 |

[Demo cara Kerja Singkat](https://youtu.be/Wl6iLyD1NzY)

# Penjelasan kode

## `Server.py`
**server.py** berfungsi sebagai pusat pengendali permainan multiplayer Tank Arena berbasis UDP yang menangani seluruh logika utama permainan, mulai dari pengelolaan koneksi pemain, pembuatan dan pengelolaan room, matchmaking, sinkronisasi data permainan, pergerakan tank dan peluru, deteksi tabrakan, perhitungan HP dan skor, hingga penentuan pemenang saat pertandingan berakhir. Server juga menyediakan fitur voice chat melalui port terpisah, mendukung reconnect ketika pemain terputus koneksi, serta memungkinkan pengguna masuk sebagai spectator untuk menonton pertandingan. Selama permainan berlangsung, server secara berkala memperbarui kondisi permainan dan mengirimkan informasi terbaru kepada seluruh pemain, sekaligus merekam setiap frame pertandingan ke dalam file replay sehingga pertandingan dapat diputar ulang dan dianalisis kembali setelah selesai.

###  Inisialisasi Server

```python
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((HOST, PORT))

VOICE_PORT = PORT + 1
voice_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
voice_sock.bind((HOST, VOICE_PORT))
```

- Membuat server UDP pada port 5555.
- Membuat port tambahan untuk voice chat.
- Menyiapkan struktur data:
    - clients → menyimpan data pemain.
    - rooms → menyimpan data room pertandingan.

### Pengiriman Data
```python
def send_to(addr, data_dict):
    sock.sendto(json.dumps(data_dict).encode('utf-8'), addr)
```
Mengirim data dalam format JSON ke client tertentu melalui UDP.

### Thread Voice Chat

```python
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
```

- Menerima paket suara dari pemain.
- Mengidentifikasi pengirim menggunakan `client_id`.
- Meneruskan audio ke lawan dalam room yang sama.
- Berjalan pada thread terpisah sehingga tidak mengganggu game utama.

### Physics Loop (30 FPS)
```python
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
```
Loop utama yang berjalan 30 kali per detik untuk memperbarui kondisi permainan.

Tugasnya meliputi:

1. Mengatur Replay
- Membuat file replay.
- Menyimpan seluruh status pertandingan ke file .jsonl.

2. Mengatur Timer Match

- Menghitung sisa waktu pertandingan.
- Menentukan pemenang ketika waktu habis.

3. Menangani Disconnect
- Mengecek apakah pemain tidak aktif terlalu lama.
- Mengubah status room menjadi waiting_reconnect.
- Menunggu pemain kembali terhubung.

4. Mengupdate Peluru

    Server menghitung:

    - Posisi baru peluru.
    - Tabrakan dengan tembok.
    - Tabrakan dengan tank lawan.
    - Pengurangan HP.
    - Penambahan skor jika lawan hancur.

5. Menyimpan Replay Frame

    Setiap frame permainan disimpan ke file replay sehingga pertandingan dapat diputar ulang.

6. Broadcast Update

    Server mengirim kondisi terbaru permainan kepada:

    - Player 1
    - Player 2
    - Spectator

    Data yang dikirim:

    - Posisi tank
    - Skor
    - Peluru
    - Timer
    - Status game over

### Command Receiver Loop

Menerima seluruh perintah dari client.

1. Validasi Client dan Ping

```python
msg_type = msg.get("type")

if msg_type == "ping":
    send_to(addr, {
        "type": "pong",
        "time": msg.get("time", 0)
    })
    continue

client_id = msg.get("client_id")

if not client_id:
    continue

if client_id not in clients:
    username = msg.get("username", "Guest")

    clients[client_id] = {
        "addr": addr,
        "room_id": None,
        "player_idx": None,
        "username": username,
        "voice_addr": None,
        "connected": True,
        "last_seen": time.time()
    }
else:
    if clients[client_id]["addr"] != addr:
        clients[client_id]["addr"] = addr

    clients[client_id]["last_seen"] = time.time()
    clients[client_id]["connected"] = True

    if msg_type == "join":
        clients[client_id]["username"] = msg.get(
            "username",
            clients[client_id].get("username", "Guest")
        )
```
mengidentifikasi client yang mengirim paket, memperbarui status koneksi client, serta menangani pengukuran ping jaringan sebelum server memproses perintah lain seperti membuat room, bergabung ke room, atau mengontrol tank.

2. Join Server
```python
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
```
- Mendaftarkan pemain baru.
- Menyimpan username.
- Menangani reconnect jika pemain sebelumnya terputus.

3. Create Room
```python
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
```
- Membuat room baru.
- Menghasilkan ID room acak.
- Menjadikan pembuat room sebagai Player 1.

4. Get Public Rooms
```python
elif msg_type == "get_public_rooms":
                pub_rooms = [{"room_id": rid, "host": r["host_username"], "status": r["status"]} for rid, r in rooms.items() if not r["is_private"]]
                send_to(addr, {"type": "public_rooms_list", "rooms": pub_rooms})
```

Mengirim daftar room publik yang tersedia.

5. Join Room dan Spectator Mode
```python
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
        contin
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
```
Ketika pemain masuk room:

- Menjadi Player 2.
- Membuat map obstacle secara acak.
- Menginisialisasi posisi tank.
- Memulai pertandingan.
- Mengirim data awal ke semua pemain.

Spectator Mode:
```python
if msg.get("as_spectator", False):
```

- Pemain dapat menonton pertandingan.
- Tidak dapat mengontrol tank.
- Tetap menerima update permainan.

6. Action (Kontrol Tank)
```python
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
                p_tank["y"] = max(10, min(HEIGHT - 50, future_y
        if msg.get("shoot") and len(r["bullets"]) < 10:
            r["bullets"].append({"owner": pidx, "x": p_tank["x"] + 20, "y": p_tank["y"] + 20, "angle": p_tank["angle"]})
```

Memproses input pemain:
- Gerakan
```
MOVE_UP
MOVE_DOWN
MOVE_LEFT
MOVE_RIGHT
```

- Rotasi
```
ROT_LEFT
ROT_RIGHT
```

- Menembak

7.  Leave Room

```python
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
```
- Menghapus spectator dari room.
- Menandai pemain sebagai disconnect.
- Mengaktifkan mode reconnect.
- Menghapus room jika pertandingan belum dimulai.

### Alur Kerja
```
Client Join
      │
      ▼
Create Room / Join Room
      │
      ▼
Match Dimulai
      │
      ▼
Player Kirim Action
(Move, Rotate, Shoot)
      │
      ▼
Server Physics Loop
- Update Peluru
- Hit Detection
- Hitung Skor
- Hitung Timer
      │
      ▼
Broadcast Update
ke Player & Spectator
      │
      ▼
Replay Disimpan
      │
      ▼
Game Over
(Timer Habis / Skor Akhir)
```

## Client.py
Secara keseluruhan, **client.py** bertugas sebagai antarmuka pemain yang menghubungkan pengguna dengan server. Client menangani pembuatan dan masuk room, menerima informasi permainan dari server, mengirim kontrol pemain (gerakan, rotasi, dan tembakan), menampilkan seluruh objek permainan menggunakan Pygame, menyediakan voice chat real-time, serta menampilkan hasil akhir pertandingan. Seluruh logika utama permainan seperti perhitungan peluru, tabrakan, skor, dan penentuan pemenang tetap diproses oleh server, sedangkan client hanya bertugas mengirim input dan menampilkan hasil yang diterima dari server.

### Inisialisasi Client
```python
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
voice_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
```

Membuat dua koneksi UDP:

- sock → komunikasi game.
- voice_sock → komunikasi voice chat.

### Identitas Pemain
```python
CLIENT_ID = str(uuid.uuid4())
```

Membuat ID unik untuk setiap pemain.
ID ini digunakan server untuk:

- mengenali pemain,
- reconnect,
- menentukan lawan,
- mengirim voice chat.

### Inisialisasi Socket Voice Chat dan Fungsi Pengiriman Pesan
```python
voice_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
voice_sock.setblocking(False)
VOICE_SERVER_PORT = SERVER_PORT + 1

def send_msg(msg_dict):
    if "client_id" not in msg_dict:
        msg_dict["client_id"] = CLIENT_ID

    try:
        sock.sendto(
            json.dumps(msg_dict).encode('utf-8'),
            (SERVER_HOST, SERVER_PORT)
        )
    except:
        pass
```

1. Inisialisasi Socket Voice Chat

Membuat socket UDP khusus untuk komunikasi suara (voice chat).
Server menggunakan dua jalur komunikasi berbeda:
```
Port 5555 -> Data permainan
Port 5556 -> Voice Chat
```
Pemisahan ini membuat pengiriman suara tidak mengganggu lalu lintas data permainan.

2. Pengaturan Non-Blocking
```python 
voice_sock.setblocking(False)
```
Mengubah socket menjadi mode non-blocking.

Artinya:
```
Jika ada data suara:
    baca data

Jika tidak ada data:
    lanjutkan program
```
Tanpa mode ini, client bisa berhenti sementara menunggu paket suara masuk sehingga permainan menjadi lag atau tidak responsif.

3. Menentukan Port Voice Server
```python
VOICE_SERVER_PORT = SERVER_PORT + 1
Fungsi
```
Menentukan port voice chat.

Karena: `SERVER_PORT = 5555` maka:
`VOICE_SERVER_PORT = 5556` Port ini digunakan untuk mengirim dan menerima audio.

### Pengiriman Pesan ke Server
```python
def send_msg(msg_dict):
```    

Menyediakan fungsi umum untuk mengirim semua jenis pesan ke server.

Contoh penggunaannya:
`send_msg({"type": "join"})`
`send_msg({"type": "create_room"})`
`send_msg({"type": "action"})`

Dengan demikian seluruh komunikasi game menggunakan satu fungsi yang sama.

### Menambahkan Client ID Otomatis
```python
if "client_id" not in msg_dict:
    msg_dict["client_id"] = CLIENT_ID
```

Menjamin setiap paket yang dikirim memiliki identitas pemain.

Contoh:

Sebelum dikirim:
```python
{
    "type": "join"
}
```
Sesudah diproses:
```python
{
    "type": "join",
    "client_id": "abc123"
}
```
Server menggunakan client_id untuk:

- mengenali pemain,
- menentukan room,
- mendukung reconnect,
- mengidentifikasi pengirim voice chat.

### Konversi Data ke JSON
```python
json.dumps(msg_dict)
```
Mengubah dictionary Python menjadi format JSON agar dapat dikirim melalui jaringan.

Contoh:

Dictionary:
```python
{
    "type": "action",
    "shoot": True
}
```
Menjadi:
```json
{
    "type":"action",
    "shoot":true
}
```
### Encoding ke Bentuk Byte
```python
.encode('utf-8')
```
Mengubah teks JSON menjadi byte karena socket hanya dapat mengirim data dalam bentuk byte.

### Mengirim Paket UDP
```python
sock.sendto(
    data,
    (SERVER_HOST, SERVER_PORT)
)
```
Mengirim paket ke server game.

Tujuan pengiriman:
```
Alamat : SERVER_HOST
Port    : 5555
```
Contoh data yang dikirim:
```
JOIN ROOM
CREATE ROOM
ACTION (MOVE)
ACTION (SHOOT)
PING
LEAVE ROOM
```
### Penanganan Error
```python
try:
    ...
except:
    pass
```
Mencegah client crash ketika terjadi masalah jaringan.

Misalnya:

- server mati,
- koneksi terputus,
- paket gagal dikirim.

Client tetap berjalan walaupun pengiriman paket gagal.

### Join ke Server
```python
send_msg({
    "type": "join",
    "username": default_username
})
```
Saat client dijalankan:
- langsung mengirim permintaan join.
- mendaftarkan username ke server.

### Inisialisasi Tampilan
```python
pygame.init()

screen = pygame.display.set_mode((800,600))
```
Menyiapkan jendela game menggunakan Pygame.
Ukuran layar: `800 x 600 pixel`

### Voice Chat
```python
if pyaudio is not None:
    try:
        p = pyaudio.PyAudio()
        audio_stream_out = p.open(format=pyaudio.paInt16, channels=1, rate=8000, output=True)
        def record_callback(in_data, f_count, t_info, status):
            if not voice_muted and app_state == STATE_PLAYING:
                try: voice_sock.sendto(CLIENT_ID.encode('utf-8') + in_data, (SERVER_HOST, VOICE_SERVER_PORT))
                except: pass
            return (None, pyaudio.paContinue)
        audio_stream_in = p.open(format=pyaudio.paInt16, channels=1, rate=8000, input=True, frames_per_buffer=512, stream_callback=record_callback)
        voice_enabled = True
        def receive_voice_thread():
            import select
            while app_state != -1:
                try:
                    r, _, _ = select.select([voice_sock], [], [], 0.1)
                    if r:
                        data, _ = voice_sock.recvfrom(2048)
                        if app_state == STATE_PLAYING and not voice_muted: audio_stream_out.write(data)
                except: pass
        threading.Thread(target=receive_voice_thread, daemon=True).start()
    except: voice_enabled = False
```
Mengaktifkan komunikasi suara antar pemain.

1. Mengirim Suara
```python
def record_callback(...):
    voice_sock.sendto(...)
```
- menangkap suara mikrofon,
- mengirim data audio ke server.

2. Menerima Suara
```python
def receive_voice_thread():
```
- menerima suara dari server,
- memutarnya melalui speaker.

Voice chat berjalan pada thread terpisah agar tidak mengganggu game.

### Menggambar Tank
```python
def draw_tank_rotated(x, y, angle, color_body, is_me):
    tank_surf = pygame.Surface((40, 40), pygame.SRCALPHA)
    pygame.draw.rect(tank_surf, color_body, (0, 0, 40, 40))
    pygame.draw.rect(tank_surf, (200, 200, 200), (20, 16, 25, 8)) 
    if is_me: pygame.draw.rect(tank_surf, (255, 255, 255), (0, 0, 40, 40), 2)
    rotated_surf = pygame.transform.rotate(tank_surf, angle)
    new_rect = rotated_surf.get_rect(center=(x + 20, y + 20))
    screen.blit(rotated_surf, new_rect.topleft)
```
Menggambar tank pada layar.

Fitur:

- warna berbeda tiap pemain,
- dapat berputar 360°,
- memberi tanda tank milik pemain sendiri.

### Thread Penerima Data Server
```python
def network_receiver_thread():
```
Thread khusus yang selalu mendengarkan paket dari server.

### Thread Penerima Data Server
```python
def network_receiver_thread():
```
Thread khusus yang selalu mendengarkan paket dari server.

1. Pong
```python
if msg_type == "pong":
```

Menghitung ping.
`Ping = waktu kirim - waktu balas`

2. Room Created
```python
elif msg_type == "room_created":
```

Menyimpan kode room yang baru dibuat.

3. Match Found
```python
elif msg_type == "match_found":
```

Saat pertandingan dimulai:

- menerima map,
- posisi tank,
- skor awal,
- timer.

Kemudian berpindah ke mode bermain.

4. Update
```python
elif msg_type == "update":
```
Menerima update permainan secara real-time:

- posisi tank,
- HP,
- peluru,
- skor,
- timer.

Data ini disimpan ke cache untuk ditampilkan.

5. Disconnect dan Reconnect
```python
elif msg_type == "opponent_disconnected":
elif msg_type == "reconnect_success":
```

Menampilkan informasi ketika:

- lawan terputus,
- lawan kembali terhubung,
- pertandingan dilanjutkan.

### Main Loop
Loop utama client. Berjalan 60 FPS.
Tugasnya:
- membaca keyboard,
- mengirim input ke server,
- menggambar tampilan,
- menerima event.

### Sistem Menu

Client memiliki 5 menu utama.

```python
STATE_MENU
STATE_WAITING
STATE_BROWSE
STATE_JOIN_PRIVATE
STATE_PLAYING
```
1. Main Menu
```python
if app_state == STATE_MENU:
```

Menampilkan:

- Create Public Room
- Create Private Room
- Browse Public Rooms
- Join Private Room
- View Match Replay

2. Waiting Room
```python
STATE_WAITING
```

Menunggu pemain lain masuk.

3. Browse Room
```python
STATE_BROWSE
```

Menampilkan daftar room publik dari server.

4. Join Private Room
```python
STATE_JOIN_PRIVATE
```

Memasukkan kode room secara manual.

### Pengiriman Input Pemain
```python
keys = pygame.key.get_pressed()
```

Membaca tombol yang ditekan pemain.

1. Menggerakkan tank.
```
W
A
S
D
```

2. Memutar tank.
```
Q
E
```

3. Menembak
```
SPACE
```

Mengirim perintah tembak ke server.

4. Voice Chat
```
V
```

Mute atau unmute voice chat.

### Render Permainan
```python
elif app_state == STATE_PLAYING:
```

Menampilkan seluruh objek permainan.

1. Obstacle
```python
for obs in map_data:
```

Menggambar tembok atau penghalang.

2. Tank
```python
for p_idx_str, p_state in state_cache.items():
```

Menggambar:

- posisi tank,
- arah tank,
- HP,
- skor.

4. Peluru'
```python
for b in bullet_list_cache:
```

Menggambar peluru yang dikirim server.

5. Timer
```python
screen.blit(...)
```

Menampilkan sisa waktu pertandingan.

### Game Over
```pyhton
if game_over:
```

Menampilkan:

- pemenang,
- skor akhir,
- kondisi disconnect,
- pesan kembali ke menu.

## Alur Kerja
```
Client Dijalankan
        │
        ▼
Koneksi ke Server UDP
        │
        ▼
Mengirim Join Request
        │
        ▼
Menampilkan Main Menu
        │
        ▼
Create Room / Join Room
        │
        ▼
Match Dimulai
        │
        ▼
Pemain Menekan Tombol
(WASD, Q, E, SPACE)
        │
        ▼
Input Dikirim ke Server
        │
        ▼
Server Menghitung Game Logic
        │
        ▼
Client Menerima Update
(Posisi, HP, Peluru, Skor)
        │
        ▼
Render Ulang Tampilan
        │
        ▼
Game Over / Keluar Room
```

## `replay_viewer.py`

Secara keseluruhan, **replay_viewer.py** berfungsi sebagai pemutar ulang pertandingan yang telah direkam server. Program membaca file replay dalam format JSON Lines (.jsonl), memuat seluruh frame permainan, lalu menampilkan kembali kondisi pertandingan secara visual menggunakan Pygame. Replay viewer menampilkan posisi tank, rotasi tank 360°, HP, peluru, skor, timer, serta hasil akhir pertandingan. Selain itu, pengguna dapat mengontrol pemutaran replay melalui fitur play/pause, percepatan, perlambatan, dan pencarian frame sehingga jalannya pertandingan dapat dianalisis kembali setelah permainan selesai.

### Fungsi Rotasi Tank
```python
def draw_tank_rotated(screen, x, y, angle, color_body, is_me=False):
```

Menggambar tank berdasarkan sudut rotasi yang tersimpan pada replay.

Fitur:

- Mendukung rotasi penuh 360°.
- Menyesuaikan arah tank dengan gameplay asli.
- Menampilkan warna berbeda untuk masing-masing pemain.

1. Proses Rotasi
```python
rotated_surf = pygame.transform.rotate(
    tank_surf,
    angle_val
)
```

Memutar gambar tank sesuai nilai sudut (angle) yang tersimpan pada frame replay.

### Membuka File Replay
```python
replay_file = sys.argv[1]
```

Mengambil lokasi file replay dari parameter command line.

Contoh: `python replay_viewer.py replay.jsonl`

### Membaca Replay
```pyhton
with open(replay_file, "r") as f:
```

Membaca seluruh isi file replay.

1. Membaca Metadata Awal
```python
if data["type"] == "init":
```

Mengambil informasi awal pertandingan:

- obstacle map,
- username pemain.

Data ini hanya dibaca sekali pada awal replay.

2. Membaca Frame Permainan
```python
elif data["type"] in ["frame", "update"]:
```

Menyimpan setiap frame permainan ke dalam list:
```python
frames.append(data)
```

Frame berisi:

- posisi tank,
- HP,
- peluru,
- skor,
- timer.
### Inisialisasi Viewer
```python
pygame.init()

screen = pygame.display.set_mode((800, 600))

```
Membuat jendela replay berukuran:

800 × 600 pixel

### Variabel Playback
```python
current_frame_idx = 0
playing = True
playback_speed = 1.0
```

Mengatur kondisi replay:

|Variabel|	Fungsi|
| :--- | :--- |
|current_frame_idx|	Frame yang sedang diputar|
|playing|	Status play/pause|
|playback_speed|	Kecepatan replay|

### Kontrol Replay
```python
for event in pygame.event.get():
```

Membaca input pengguna.

1. Play / Pause
```python
if event.key == pygame.K_SPACE:
```

Menghentikan atau melanjutkan replay.

2. Maju Cepat
```python
pygame.K_RIGHT
```

Melompat maju 60 frame.

3. Mundur
```python
pygame.K_LEFT
```

Melompat mundur 60 frame.

4. Percepat Replay
```python
pygame.K_UP
```

Meningkatkan kecepatan: `1x → 2x → 4x`

5. Perlambat Replay
```python
pygame.K_DOWN
```

Mengurangi kecepatan: `1x → 0.5x → 0.25x`

### Pemutaran Frame
```python
if playing:
    current_frame_idx += ...
```

Memindahkan replay ke frame berikutnya sesuai kecepatan yang dipilih.

### Render Map
```python
for obs in map_data:
```

Menggambar seluruh obstacle yang digunakan saat pertandingan berlangsung.

### Render Tank
```python
for p_idx_str, p_state in state.items():
```

Menggambar tank berdasarkan data replay:

- posisi X dan Y,
- sudut rotasi,
- warna pemain.

1. Menampilkan HP
```python
hp_ratio = hp / 100
```

Menggambar HP bar di atas tank.

Hijau: `HP tinggi`

Merah: `HP rendah`

### Render Peluru
```python
bullet_list = frame.get("bullets", [])
```

Mengambil seluruh peluru dari frame replay.

1. Menggambar Peluru
```python
for b in bullet_list:
    pygame.draw.circle(...)
```

Menampilkan posisi peluru sesuai kondisi asli pertandingan.

### Render HUD
```python
round_text = ...
score_text = ...
```

Menampilkan informasi pertandingan:

- sisa waktu,
- skor kedua pemain,
- nama pemain.

Contoh:
```
Sisa Waktu: 25s
PlayerA 3 - 2 PlayerB
```
### Menampilkan Game Over
```python
if game_over:
```
Menampilkan pesan:

`PERTANDINGAN SELESAI!`

ketika replay mencapai akhir pertandingan.

### Progress Bar Replay
```python
progress = current_frame_idx / len(frames)
```

Menghitung persentase replay yang sudah diputar.

1. Menggambar Progress Bar
```python
pygame.draw.rect(...)
```
Menampilkan bar kemajuan replay di bagian bawah layar.

### Alur Kerja
```
File Replay (.jsonl)
        │
        ▼
Membaca Data Replay
        │
        ▼
Menyimpan Frame ke Memori
        │
        ▼
Inisialisasi Pygame
        │
        ▼
Memutar Frame Satu per Satu
        │
        ▼
Render:
- Map
- Tank
- HP
- Peluru
- Skor
- Timer
        │
        ▼
Kontrol Replay
(Play, Pause, Seek, Speed)
        │
        ▼
Replay Selesai
```
