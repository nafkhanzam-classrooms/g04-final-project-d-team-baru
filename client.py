import pygame
import socket
import json
import uuid
import time
import sys
import os
import threading

try:
    import pyaudio
except ImportError:
    print("Warning: pyaudio not installed. Voice chat will be disabled.")
    print("To enable, run: pip install pyaudio")
    pyaudio = None

# Server Configuration
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5555

# --- RECONNECT HANDLING SETUP ---
args = sys.argv[1:]
CLIENT_ID = None

if "--id" in args:
    idx = args.index("--id")
    if idx + 1 < len(args):
        CLIENT_ID = args[idx + 1]

for a in args:
    if not a.startswith("--") and a != CLIENT_ID:
        SERVER_HOST = a
        break

if not CLIENT_ID:
    CLIENT_ID = str(uuid.uuid4())
    print(f"Generated new Client ID: {CLIENT_ID}")
    print(f"To test reconnect, run this again with: python client.py --id {CLIENT_ID}")
else:
    print(f"Reconnecting with Client ID: {CLIENT_ID}")

# Socket Setup
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setblocking(False)

# Voice Socket Setup
voice_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
voice_sock.setblocking(False)
VOICE_SERVER_PORT = SERVER_PORT + 1

def send_msg(msg_dict):
    try:
        if "client_id" not in msg_dict:
            msg_dict["client_id"] = CLIENT_ID
        sock.sendto(json.dumps(msg_dict).encode('utf-8'), (SERVER_HOST, SERVER_PORT))
    except Exception:
        pass

# Pygame Setup
pygame.init()
screen = pygame.display.set_mode((800, 600))
pygame.display.set_caption("Simple UDP Multiplayer Tank")
clock = pygame.time.Clock()
font = pygame.font.SysFont("Arial", 20)
big_font = pygame.font.SysFont("Arial", 36)
huge_font = pygame.font.SysFont("Arial", 72)

# App States
STATE_LOGIN = 0
STATE_MENU = 1
STATE_CREATE_PRIVATE = 2
STATE_WAITING = 3
STATE_BROWSE = 4
STATE_JOIN_PRIVATE = 5
STATE_PLAYING = 6
app_state = STATE_LOGIN

username_input = ""
password_input = ""
room_id_input = ""
input_field = 0
public_rooms = []
selected_room_idx = 0
join_error_msg = ""
my_room_id = ""

# Local State
my_idx = None
is_spectator = False
x, y = 400, 300
speed = 5
my_angle = "UP"
my_bullets = [] # [{"x": ..., "y": ..., "dx": ..., "dy": ...}]
bullet_speed = 10

map_data = [] # List of {"x", "y", "w", "h"}
my_round = 1
score = {"1": 0, "2": 0}
game_over = False
winner = None
server_leaderboard = []
show_leaderboard = False
last_leaderboard_req = 0

# Game State Cache
state_cache = {
    "1": {"x": -100, "y": -100, "angle": "UP", "bullets": [], "hp": 100},
    "2": {"x": -100, "y": -100, "angle": "UP", "bullets": [], "hp": 100}
}

ping_ms = 0
last_ping_send = 0
last_join_send = 0

running = True
print("Game Client Started.")

voice_enabled = False
voice_muted = False
audio_stream_out = None
audio_stream_in = None
p = None

if pyaudio is not None:
    try:
        p = pyaudio.PyAudio()
        
        # Format: 8000 Hz, 1 channel, 16-bit
        audio_stream_out = p.open(format=pyaudio.paInt16, channels=1, rate=8000, output=True)
        
        # Input callback
        def record_callback(in_data, frame_count, time_info, status):
            if not voice_muted and app_state == STATE_PLAYING:
                try:
                    packet = CLIENT_ID.encode('utf-8') + in_data
                    voice_sock.sendto(packet, (SERVER_HOST, VOICE_SERVER_PORT))
                except Exception:
                    pass
            return (None, pyaudio.paContinue)
            
        audio_stream_in = p.open(format=pyaudio.paInt16, channels=1, rate=8000, input=True, frames_per_buffer=512, stream_callback=record_callback)
        audio_stream_in.start_stream()
        voice_enabled = True
        
        # Receiver thread
        def receive_voice_thread():
            import select
            while running:
                try:
                    r, _, _ = select.select([voice_sock], [], [], 0.1)
                    if r:
                        data, _ = voice_sock.recvfrom(2048)
                        if audio_stream_out and app_state == STATE_PLAYING:
                            audio_stream_out.write(data)
                except Exception:
                    pass
                    
        threading.Thread(target=receive_voice_thread, daemon=True).start()
        print("Voice Chat Initialized on Port", VOICE_SERVER_PORT)
        
    except Exception as e:
        print(f"Failed to initialize voice: {e}")
        voice_enabled = False

def collides_with_map(rect):
    for obs in map_data:
        obs_rect = pygame.Rect(obs["x"], obs["y"], obs["w"], obs["h"])
        if rect.colliderect(obs_rect):
            return True
    return False

while running:
    # Event Handling
    space_pressed_this_frame = False
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
            
        elif event.type == pygame.KEYDOWN:
            if app_state == STATE_LOGIN:
                if event.key == pygame.K_RETURN:
                    if len(username_input.strip()) > 0:
                        send_msg({"type": "join", "client_id": CLIENT_ID, "username": username_input.strip()})
                        app_state = STATE_MENU
                elif event.key == pygame.K_BACKSPACE:
                    username_input = username_input[:-1]
                elif event.key == pygame.K_TAB:
                    show_leaderboard = not show_leaderboard
                    if show_leaderboard:
                        send_msg({"type": "get_leaderboard", "client_id": CLIENT_ID})
                else:
                    if len(username_input) < 12 and event.unicode.isprintable():
                        username_input += event.unicode
                        
            elif app_state == STATE_MENU:
                if event.key == pygame.K_1:
                    send_msg({"type": "create_room", "is_private": False})
                elif event.key == pygame.K_2:
                    password_input = ""
                    app_state = STATE_CREATE_PRIVATE
                elif event.key == pygame.K_3:
                    send_msg({"type": "get_public_rooms"})
                    app_state = STATE_BROWSE
                elif event.key == pygame.K_4:
                    room_id_input = ""
                    password_input = ""
                    input_field = 0
                    join_error_msg = ""
                    app_state = STATE_JOIN_PRIVATE
                    
            elif app_state == STATE_CREATE_PRIVATE:
                if event.key == pygame.K_RETURN:
                    send_msg({"type": "create_room", "is_private": True, "password": password_input.strip()})
                elif event.key == pygame.K_ESCAPE:
                    app_state = STATE_MENU
                elif event.key == pygame.K_BACKSPACE:
                    password_input = password_input[:-1]
                else:
                    if len(password_input) < 12 and event.unicode.isprintable():
                        password_input += event.unicode
                        
            elif app_state == STATE_BROWSE:
                if event.key == pygame.K_ESCAPE:
                    app_state = STATE_MENU
                elif event.key == pygame.K_UP:
                    selected_room_idx = max(0, selected_room_idx - 1)
                elif event.key == pygame.K_DOWN:
                    selected_room_idx = min(max(0, len(public_rooms) - 1), selected_room_idx + 1)
                elif event.key == pygame.K_p:
                    if public_rooms:
                        send_msg({"type": "join_room", "room_id": public_rooms[selected_room_idx]["room_id"], "password": "", "as_spectator": False})
                elif event.key == pygame.K_s:
                    if public_rooms:
                        send_msg({"type": "join_room", "room_id": public_rooms[selected_room_idx]["room_id"], "password": "", "as_spectator": True})
                        
            elif app_state == STATE_JOIN_PRIVATE:
                if event.key == pygame.K_ESCAPE:
                    app_state = STATE_MENU
                elif event.key == pygame.K_TAB:
                    input_field = 1 - input_field
                elif event.key == pygame.K_p:
                    send_msg({"type": "join_room", "room_id": room_id_input.strip(), "password": password_input.strip(), "as_spectator": False})
                elif event.key == pygame.K_s:
                    send_msg({"type": "join_room", "room_id": room_id_input.strip(), "password": password_input.strip(), "as_spectator": True})
                elif event.key == pygame.K_BACKSPACE:
                    if input_field == 0:
                        room_id_input = room_id_input[:-1]
                    else:
                        password_input = password_input[:-1]
                else:
                    if input_field == 0 and len(room_id_input) < 4 and event.unicode.isprintable():
                        room_id_input += event.unicode
                    elif input_field == 1 and len(password_input) < 12 and event.unicode.isprintable():
                        password_input += event.unicode
                        
            elif app_state == STATE_WAITING:
                if event.key == pygame.K_ESCAPE:
                    send_msg({"type": "leave_room"})
                    app_state = STATE_MENU
                    my_room_id = ""
                    my_idx = None
                    
            elif app_state == STATE_PLAYING:
                if event.key == pygame.K_ESCAPE:
                    send_msg({"type": "leave_room"})
                    app_state = STATE_MENU
                    my_room_id = ""
                    my_idx = None
                    is_spectator = False
                    game_over = False
                    winner = None
                elif not is_spectator:
                    if event.key == pygame.K_SPACE:
                        space_pressed_this_frame = True
                    elif event.key == pygame.K_v:
                        voice_muted = not voice_muted
            
    # --- TERIMA PAKET DARI SERVER ---
    try:
        while True:
            data, _ = sock.recvfrom(4096)
            msg = json.loads(data.decode('utf-8'))
            msg_type = msg.get("type")
            
            if msg_type == "pong":
                ping_ms = int((time.time() - msg.get("time", 0)) * 1000)
                
            elif msg_type == "room_created":
                my_room_id = msg.get("room_id")
                app_state = STATE_WAITING
                
            elif msg_type == "public_rooms_list":
                public_rooms = msg.get("rooms", [])
                selected_room_idx = 0
                
            elif msg_type == "join_error":
                join_error_msg = msg.get("msg", "Error joining room")
                
            elif msg_type == "match_found" and app_state in [STATE_WAITING, STATE_BROWSE, STATE_JOIN_PRIVATE, STATE_PLAYING]:
                if my_idx is None or is_spectator:
                    my_idx = msg.get("player_idx")
                    map_data = msg.get("map", [])
                    my_round = msg.get("round", 1)
                    score = msg.get("score", {"1": 0, "2": 0})
                    
                    if my_idx == "spectator":
                        is_spectator = True
                        print(f"Match found! Spectating...")
                        if "state" in msg:
                            state_cache = msg["state"]
                    else:
                        is_spectator = False
                        print(f"Match found! I am Player {my_idx}")
                        # Set posisi awal
                        if my_idx == 1:
                            x, y = 100, 300
                            my_angle = "RIGHT"
                        else:
                            x, y = 700, 300
                            my_angle = "LEFT"
                            
                    app_state = STATE_PLAYING
                        
            elif msg_type == "round_reset":
                my_round = msg.get("round", 1)
                score = msg.get("score", score)
                map_data = msg.get("map", [])
                state_cache = msg.get("state", state_cache)
                my_bullets.clear()
                # Reset posisi lokal
                if my_idx == 1:
                    x, y = 100, 300
                    my_angle = "RIGHT"
                else:
                    x, y = 700, 300
                    my_angle = "LEFT"
                    
            elif msg_type == "update":
                state_cache = msg.get("state", state_cache)
                score = msg.get("score", score)
                my_round = msg.get("round", my_round)
                game_over = msg.get("game_over", game_over)
                winner = msg.get("winner", winner)
                if "leaderboard" in msg:
                    server_leaderboard = msg["leaderboard"]
                    
            elif msg_type == "leaderboard_data":
                server_leaderboard = msg.get("leaderboard", [])
                
    except BlockingIOError:
        pass
    except json.JSONDecodeError:
        pass
    except Exception as e:
        print(f"Error receiving: {e}")

    now = time.time()
    
    # Ping di background
    if now - last_ping_send > 1.0:
        send_msg({"type": "ping", "time": now})
        last_ping_send = now

    screen.fill((30, 30, 30))

    if app_state == STATE_LOGIN:
        # Render Login UI
        title_text = huge_font.render("TANK BATTLE", True, (255, 255, 255))
        prompt_text = big_font.render("Enter Username:", True, (200, 200, 200))
        input_text = big_font.render(username_input + ("|" if int(time.time() * 2) % 2 == 0 else ""), True, (255, 255, 0))
        help_text = font.render("Press ENTER to join | Press TAB for Leaderboard", True, (100, 100, 100))
        
        screen.blit(title_text, (400 - title_text.get_width()//2, 80))
        screen.blit(prompt_text, (400 - prompt_text.get_width()//2, 180))
        
        # Draw input box
        input_box = pygame.Rect(250, 230, 300, 50)
        pygame.draw.rect(screen, (50, 50, 50), input_box)
        pygame.draw.rect(screen, (255, 255, 255), input_box, 2)
        screen.blit(input_text, (input_box.x + 10, input_box.y + 5))
        
        screen.blit(help_text, (400 - help_text.get_width()//2, 290))
        
        if show_leaderboard:
            # Refresh every 2 seconds
            if now - last_leaderboard_req > 2.0:
                send_msg({"type": "get_leaderboard", "client_id": CLIENT_ID})
                last_leaderboard_req = now
                
            lb_title = big_font.render("--- GLOBAL LEADERBOARD ---", True, (255, 215, 0))
            screen.blit(lb_title, (400 - lb_title.get_width()//2, 350))
            start_y = 400
            for i, (uname, wins) in enumerate(server_leaderboard):
                lb_item = font.render(f"#{i+1}  {uname} : {wins} Wins", True, (200, 200, 200))
                screen.blit(lb_item, (400 - lb_item.get_width()//2, start_y + (i * 30)))
                
    elif app_state == STATE_MENU:
        title_text = huge_font.render("MAIN MENU", True, (255, 255, 255))
        screen.blit(title_text, (400 - title_text.get_width()//2, 80))
        
        opt1 = big_font.render("[1] Create Public Room", True, (200, 200, 200))
        opt2 = big_font.render("[2] Create Private Room", True, (200, 200, 200))
        opt3 = big_font.render("[3] Browse Public Rooms", True, (200, 200, 200))
        opt4 = big_font.render("[4] Join Private Room", True, (200, 200, 200))
        
        screen.blit(opt1, (400 - opt1.get_width()//2, 200))
        screen.blit(opt2, (400 - opt2.get_width()//2, 260))
        screen.blit(opt3, (400 - opt3.get_width()//2, 320))
        screen.blit(opt4, (400 - opt4.get_width()//2, 380))
        
    elif app_state == STATE_CREATE_PRIVATE:
        title = big_font.render("Create Private Room", True, (255, 255, 255))
        prompt = font.render("Enter Password for Room:", True, (200, 200, 200))
        input_text = big_font.render(password_input + ("|" if int(time.time() * 2) % 2 == 0 else ""), True, (255, 255, 0))
        help_text = font.render("Press ENTER to Create | ESC to Cancel", True, (100, 100, 100))
        
        screen.blit(title, (400 - title.get_width()//2, 100))
        screen.blit(prompt, (400 - prompt.get_width()//2, 180))
        
        input_box = pygame.Rect(250, 230, 300, 50)
        pygame.draw.rect(screen, (50, 50, 50), input_box)
        pygame.draw.rect(screen, (255, 255, 255), input_box, 2)
        screen.blit(input_text, (input_box.x + 10, input_box.y + 5))
        screen.blit(help_text, (400 - help_text.get_width()//2, 320))
        
    elif app_state == STATE_WAITING:
        text = big_font.render("Waiting for opponent...", True, (255, 255, 255))
        id_text = big_font.render(f"Room ID: {my_room_id}", True, (255, 255, 0))
        help_text = font.render("Press ESC to Cancel & Leave", True, (100, 100, 100))
        screen.blit(text, (400 - text.get_width()//2, 250))
        screen.blit(id_text, (400 - id_text.get_width()//2, 320))
        screen.blit(help_text, (400 - help_text.get_width()//2, 400))
        
    elif app_state == STATE_BROWSE:
        title = big_font.render("Public Rooms", True, (255, 255, 255))
        screen.blit(title, (400 - title.get_width()//2, 80))
        
        if not public_rooms:
            no_text = font.render("No public rooms available.", True, (150, 150, 150))
            screen.blit(no_text, (400 - no_text.get_width()//2, 200))
        else:
            for i, r in enumerate(public_rooms):
                color = (255, 255, 0) if i == selected_room_idx else (200, 200, 200)
                r_text = font.render(f"[{r['room_id']}] Host: {r['host']}", True, color)
                screen.blit(r_text, (250, 150 + (i * 30)))
                
        help_text = font.render("Up/Down to Select | P to join Player | S to join Spectator", True, (100, 100, 100))
        screen.blit(help_text, (400 - help_text.get_width()//2, 500))
        if join_error_msg:
            err = font.render(join_error_msg, True, (255, 0, 0))
            screen.blit(err, (400 - err.get_width()//2, 530))
            
    elif app_state == STATE_JOIN_PRIVATE:
        title = big_font.render("Join Private Room", True, (255, 255, 255))
        screen.blit(title, (400 - title.get_width()//2, 80))
        
        c0 = (255, 255, 255) if input_field == 0 else (100, 100, 100)
        c1 = (255, 255, 255) if input_field == 1 else (100, 100, 100)
        
        l1 = font.render("Room ID (4 digits):", True, c0)
        i1 = big_font.render(room_id_input + ("|" if input_field==0 and int(time.time()*2)%2==0 else ""), True, (255, 255, 0))
        l2 = font.render("Password:", True, c1)
        i2 = big_font.render(password_input + ("|" if input_field==1 and int(time.time()*2)%2==0 else ""), True, (255, 255, 0))
        
        screen.blit(l1, (250, 180))
        b1 = pygame.Rect(250, 210, 300, 50)
        pygame.draw.rect(screen, (50, 50, 50), b1)
        pygame.draw.rect(screen, c0, b1, 2)
        screen.blit(i1, (b1.x+10, b1.y+5))
        
        screen.blit(l2, (250, 280))
        b2 = pygame.Rect(250, 310, 300, 50)
        pygame.draw.rect(screen, (50, 50, 50), b2)
        pygame.draw.rect(screen, c1, b2, 2)
        screen.blit(i2, (b2.x+10, b2.y+5))
        
        help_text = font.render("TAB to switch | P for Player | S for Spectator | ESC to Cancel", True, (100, 100, 100))
        screen.blit(help_text, (400 - help_text.get_width()//2, 450))
        
        if join_error_msg:
            err = font.render(join_error_msg, True, (255, 0, 0))
            screen.blit(err, (400 - err.get_width()//2, 490))
        
    elif app_state == STATE_PLAYING:
        
        if game_over:
            # Tampilkan Layar Game Over & Leaderboard
            text_str = "YOU WIN!" if winner == my_idx else "YOU LOSE!"
            color = (0, 255, 0) if winner == my_idx else (255, 0, 0)
            
            go_text = huge_font.render(text_str, True, color)
            score_text = big_font.render(f"Final Score: P1 {score['1']} - {score['2']} P2", True, (255, 255, 255))
            
            screen.blit(go_text, (400 - go_text.get_width()//2, 100))
            screen.blit(score_text, (400 - score_text.get_width()//2, 200))
            
            # Draw Leaderboard
            lb_title = big_font.render("--- GLOBAL LEADERBOARD ---", True, (255, 215, 0))
            screen.blit(lb_title, (400 - lb_title.get_width()//2, 300))
            
            start_y = 350
            for i, (uname, wins) in enumerate(server_leaderboard):
                lb_item = font.render(f"#{i+1}  {uname} : {wins} Wins", True, (200, 200, 200))
                screen.blit(lb_item, (400 - lb_item.get_width()//2, start_y + (i * 30)))
            
        else:
            if not is_spectator:
                # --- INPUT & MOVEMENT (Hanya jika belum game over) ---
                keys = pygame.key.get_pressed()
                dx, dy = 0, 0
                if keys[pygame.K_w] or keys[pygame.K_UP]: 
                    dy -= speed
                    my_angle = "UP"
                elif keys[pygame.K_s] or keys[pygame.K_DOWN]: 
                    dy += speed
                    my_angle = "DOWN"
                elif keys[pygame.K_a] or keys[pygame.K_LEFT]: 
                    dx -= speed
                    my_angle = "LEFT"
                elif keys[pygame.K_d] or keys[pygame.K_RIGHT]: 
                    dx += speed
                    my_angle = "RIGHT"
                    
                # Pergerakan X dengan deteksi dinding
                if dx != 0:
                    new_rect = pygame.Rect(x + dx, y, 40, 40)
                    if not collides_with_map(new_rect):
                        x += dx
                # Pergerakan Y dengan deteksi dinding
                if dy != 0:
                    new_rect = pygame.Rect(x, y + dy, 40, 40)
                    if not collides_with_map(new_rect):
                        y += dy
                        
                # Batasi agar tidak keluar layar
                x = max(0, min(800 - 40, x))
                y = max(0, min(600 - 40, y))
                
                # --- SHOOTING ---
                if space_pressed_this_frame:
                    bx, by = x + 20, y + 20 # Tengah tank
                    bdx, bdy = 0, 0
                    if my_angle == "UP": bdy = -bullet_speed
                    elif my_angle == "DOWN": bdy = bullet_speed
                    elif my_angle == "LEFT": bdx = -bullet_speed
                    elif my_angle == "RIGHT": bdx = bullet_speed
                    
                    my_bullets.append({"x": bx, "y": by, "dx": bdx, "dy": bdy})
                    
                # Update posisi peluru sendiri
                active_bullets = []
                enemy_idx = "2" if my_idx == 1 else "1"
                enemy_state = state_cache.get(enemy_idx, {})
                enemy_rect = pygame.Rect(enemy_state.get("x", -100), enemy_state.get("y", -100), 40, 40)
                
                for b in my_bullets:
                    b["x"] += b["dx"]
                    b["y"] += b["dy"]
                    b_rect = pygame.Rect(b["x"] - 3, b["y"] - 3, 6, 6)
                    
                    # Cek kena musuh
                    if b_rect.colliderect(enemy_rect):
                        send_msg({"type": "hit", "client_id": CLIENT_ID, "target": int(enemy_idx)})
                        continue # Peluru hancur
                        
                    # Cek kena dinding atau keluar layar
                    if not collides_with_map(b_rect) and 0 <= b["x"] <= 800 and 0 <= b["y"] <= 600:
                        active_bullets.append(b)
                        
                my_bullets = active_bullets
    
                # Kirim posisi (state) ke server (beserta peluru)
                send_msg({
                    "type": "state", 
                    "client_id": CLIENT_ID, 
                    "x": x, 
                    "y": y, 
                    "angle": my_angle,
                    "bullets": [{"x": b["x"], "y": b["y"]} for b in my_bullets]
                })
            
            # --- GAMBAR PETA (OBSTACLES) ---
            for obs in map_data:
                pygame.draw.rect(screen, (100, 100, 100), (obs["x"], obs["y"], obs["w"], obs["h"]))
                pygame.draw.rect(screen, (150, 150, 150), (obs["x"], obs["y"], obs["w"], obs["h"]), 2)

            # --- GAMBAR PEMAIN, DARAH & PELURU ---
            for p_idx_str, p_state in state_cache.items():
                color = (255, 50, 50) if p_idx_str == "1" else (50, 50, 255)
                
                px = x if int(p_idx_str) == my_idx else p_state.get("x", -100)
                py = y if int(p_idx_str) == my_idx else p_state.get("y", -100)
                pangle = my_angle if int(p_idx_str) == my_idx else p_state.get("angle", "UP")
                
                rect = pygame.Rect(px, py, 40, 40)
                pygame.draw.rect(screen, color, rect)
                
                # Moncong tank
                barrel_length = 25
                barrel_width = 8
                cx, cy = px + 20, py + 20 # Center
                if pangle == "UP":
                    pygame.draw.rect(screen, color, (cx - barrel_width//2, py - barrel_length + 10, barrel_width, barrel_length))
                elif pangle == "DOWN":
                    pygame.draw.rect(screen, color, (cx - barrel_width//2, cy, barrel_width, barrel_length))
                elif pangle == "LEFT":
                    pygame.draw.rect(screen, color, (px - barrel_length + 10, cy - barrel_width//2, barrel_length, barrel_width))
                elif pangle == "RIGHT":
                    pygame.draw.rect(screen, color, (cx, cy - barrel_width//2, barrel_length, barrel_width))

                if int(p_idx_str) == my_idx:
                    pygame.draw.rect(screen, (255, 255, 255), rect, 2)
                    
                # Health Bar
                hp = p_state.get("hp", 100)
                hp_ratio = max(0, min(100, hp)) / 100
                pygame.draw.rect(screen, (255, 0, 0), (px, py - 12, 40, 6))
                pygame.draw.rect(screen, (0, 255, 0), (px, py - 12, int(40 * hp_ratio), 6))
                    
                # Gambar peluru
                pbullets = my_bullets if int(p_idx_str) == my_idx else p_state.get("bullets", [])
                for b in pbullets:
                    pygame.draw.circle(screen, (255, 255, 0), (int(b["x"]), int(b["y"])), 4)

        # UI: Round dan Score (Tengah Atas)
        if my_idx is not None:
            if is_spectator:
                spec_text = big_font.render("[ SPECTATOR MODE ]", True, (255, 255, 0))
                screen.blit(spec_text, (400 - spec_text.get_width()//2, 10))
                round_text = font.render(f"Round {my_round}/5", True, (255, 255, 255))
                score_text = font.render(f"P1 (Red) {score['1']} - {score['2']} P2 (Blue)", True, (200, 200, 200))
                screen.blit(round_text, (400 - round_text.get_width()//2, 50))
                screen.blit(score_text, (400 - score_text.get_width()//2, 80))
            else:
                round_text = big_font.render(f"Round {my_round}/5", True, (255, 255, 255))
                score_text = big_font.render(f"P1 (Red) {score['1']} - {score['2']} P2 (Blue)", True, (200, 200, 200))
                screen.blit(round_text, (400 - round_text.get_width()//2, 10))
                screen.blit(score_text, (400 - score_text.get_width()//2, 50))

    # UI Umum: Ping dan ID
    color_ping = (0, 255, 0) if ping_ms < 100 else (255, 255, 0) if ping_ms < 200 else (255, 0, 0)
    ping_text = font.render(f"Ping: {ping_ms} ms", True, color_ping)
    screen.blit(ping_text, (10, 10))
    
    id_text = font.render(f"ID: {CLIENT_ID[:8]}...", True, (150, 150, 150))
    screen.blit(id_text, (10, 35))

    if voice_enabled:
        v_color = (255, 0, 0) if voice_muted else (0, 255, 0)
        v_str = "Voice: Muted (V)" if voice_muted else "Voice: Active (V)"
        v_text = font.render(v_str, True, v_color)
        screen.blit(v_text, (10, 60))
    else:
        v_text = font.render("Voice: Disabled (No PyAudio)", True, (150, 150, 150))
        screen.blit(v_text, (10, 60))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
if voice_enabled and p:
    audio_stream_in.stop_stream()
    audio_stream_in.close()
    audio_stream_out.close()
    p.terminate()
sys.exit()
