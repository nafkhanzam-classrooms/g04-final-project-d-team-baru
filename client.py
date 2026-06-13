import pygame
import socket
import json
import uuid
import time
import sys
import threading
import os

try: import pyaudio
except: pyaudio = None

SERVER_HOST = '127.0.0.1'
SERVER_PORT = 5555

args = sys.argv[1:]
CLIENT_ID = None
if "--id" in args:
    idx = args.index("--id")
    if idx + 1 < len(args): CLIENT_ID = args[idx + 1]
if not CLIENT_ID: CLIENT_ID = str(uuid.uuid4())

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setblocking(True)

voice_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
voice_sock.setblocking(False)
VOICE_SERVER_PORT = SERVER_PORT + 1

def send_msg(msg_dict):
    if "client_id" not in msg_dict: msg_dict["client_id"] = CLIENT_ID
    try: sock.sendto(json.dumps(msg_dict).encode('utf-8'), (SERVER_HOST, SERVER_PORT))
    except: pass

default_username = f"Player_{CLIENT_ID[:8]}"
send_msg({"type": "join", "username": default_username})

pygame.init()
screen = pygame.display.set_mode((800, 600))
pygame.display.set_caption("Tank Arena - Mode Kode Room")
clock = pygame.time.Clock()
font = pygame.font.SysFont("Arial", 20)
big_font = pygame.font.SysFont("Arial", 36)
huge_font = pygame.font.SysFont("Arial", 50) 

STATE_MENU, STATE_WAITING, STATE_BROWSE, STATE_JOIN_PRIVATE, STATE_PLAYING = 0, 1, 2, 3, 4
app_state = STATE_MENU

room_code_input = ""
selected_room_idx = 0
public_rooms = []
join_error_msg, my_room_id, my_idx = "", "", None
is_spectator, game_over, winner = False, False, None
ping_ms, last_ping_send = 0, 0
disconnect_alert = ""

map_data, game_timer = [], 60
score = {"1": 0, "2": 0}
state_cache = {"1": {"x": -100, "y": -100, "angle": 0, "hp": 100}, "2": {"x": -100, "y": -100, "angle": 180, "hp": 100}}
bullet_list_cache = []

# --- VOICE LOGIC ---
voice_enabled, voice_muted = False, False
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

def draw_tank_rotated(x, y, angle, color_body, is_me):
    tank_surf = pygame.Surface((40, 40), pygame.SRCALPHA)
    pygame.draw.rect(tank_surf, color_body, (0, 0, 40, 40))
    pygame.draw.rect(tank_surf, (200, 200, 200), (20, 16, 25, 8)) 
    if is_me: pygame.draw.rect(tank_surf, (255, 255, 255), (0, 0, 40, 40), 2)
    rotated_surf = pygame.transform.rotate(tank_surf, angle)
    new_rect = rotated_surf.get_rect(center=(x + 20, y + 20))
    screen.blit(rotated_surf, new_rect.topleft)

def network_receiver_thread():
    global map_data, game_timer, score, state_cache, bullet_list_cache, disconnect_alert
    global my_idx, is_spectator, game_over, winner, my_room_id, app_state, join_error_msg
    global ping_ms, public_rooms
    
    while True:
        try:
            data, _ = sock.recvfrom(4096)
            msg = json.loads(data.decode('utf-8'))
            msg_type = msg.get("type")
            
            if msg_type == "pong": ping_ms = int((time.time() - msg.get("time", 0)) * 1000)
            elif msg_type == "room_created": my_room_id = msg.get("room_id"); app_state = STATE_WAITING
            elif msg_type == "public_rooms_list": public_rooms = msg.get("rooms", [])
            elif msg_type == "join_error": join_error_msg = msg.get("msg", "Error")
            elif msg_type == "match_found":
                my_idx = msg.get("player_idx")
                map_data = msg.get("map", [])
                score = msg.get("score", {"1": 0, "2": 0})
                is_spectator = (my_idx == "spectator")
                state_cache = msg.get("state", state_cache)
                bullet_list_cache = msg.get("bullets", [])
                game_timer = msg.get("timer", game_timer)
                disconnect_alert = ""
                app_state = STATE_PLAYING
            elif msg_type == "update":
                # Proteksi ekstra: hanya perbarui data jika paket server terisi valid
                if msg.get("state"): state_cache = msg.get("state")
                if msg.get("score"): score = msg.get("score")
                bullet_list_cache = msg.get("bullets", [])
                game_over = msg.get("game_over", game_over)
                winner = msg.get("winner", winner)
                game_timer = msg.get("timer", game_timer)
                if msg.get("map"): map_data = msg.get("map")
                
                # JANGAN langsung hapus disconnect_alert jika game_over bernilai True
                if not game_over:
                    disconnect_alert = msg.get("disconnect_alert", "")
                    
            elif msg_type == "opponent_disconnected":
                disconnect_alert = msg.get("msg", "Lawan terputus!")
                game_over = True
            elif msg_type == "opponent_reconnected":
                disconnect_alert = ""
                game_over = False
            elif msg_type == "reconnect_success":
                my_idx = msg.get("player_idx")
                map_data = msg.get("map", map_data)
                score = msg.get("score", score)
                state_cache = msg.get("state", state_cache)
                bullet_list_cache = msg.get("bullets", bullet_list_cache)
                game_over = msg.get("game_over", False)
                winner = msg.get("winner")
                game_timer = msg.get("timer", game_timer)
                disconnect_alert = ""
                app_state = STATE_PLAYING
                is_spectator = False
            elif msg_type == "opponent_timeout":
                disconnect_alert = msg.get("msg", "Pertandingan berakhir.")
                game_over = True
            elif msg_type == "spectator_waiting":
                my_idx = "spectator"
                is_spectator = True
                app_state = STATE_PLAYING
                game_over = False
        except: pass

threading.Thread(target=network_receiver_thread, daemon=True).start()

# --- MAIN RUN LOOP ---
running = True
while running:
    space_pressed_this_frame = False
    for event in pygame.event.get():
        if event.type == pygame.QUIT: running = False
        elif event.type == pygame.KEYDOWN:
            if app_state == STATE_MENU:
                if event.key == pygame.K_1: send_msg({"type": "create_room", "is_private": False})
                elif event.key == pygame.K_2:
                    join_error_msg = ""
                    send_msg({"type": "create_room", "is_private": True})
                    app_state = STATE_WAITING
                elif event.key == pygame.K_3: send_msg({"type": "get_public_rooms"}); app_state = STATE_BROWSE
                elif event.key == pygame.K_4: room_code_input = ""; join_error_msg = ""; app_state = STATE_JOIN_PRIVATE
                elif event.key == pygame.K_5:
                    running = False # Tutup jendela client.py
                    pygame.quit()
                    # Jalankan script viewer rekaman secara otomatis lewat OS terminal
                    os.system("python replay_viewer.py")
                    sys.exit()
            elif app_state == STATE_BROWSE:
                if event.key == pygame.K_ESCAPE: app_state = STATE_MENU
                elif event.key == pygame.K_UP: selected_room_idx = max(0, selected_room_idx - 1)
                elif event.key == pygame.K_DOWN: selected_room_idx = min(max(0, len(public_rooms)-1), selected_room_idx + 1)
                elif event.key == pygame.K_p and public_rooms: send_msg({"type": "join_room", "room_id": public_rooms[selected_room_idx]["room_id"], "as_spectator": False})
                elif event.key == pygame.K_s and public_rooms: send_msg({"type": "join_room", "room_id": public_rooms[selected_room_idx]["room_id"], "as_spectator": True})
            elif app_state == STATE_JOIN_PRIVATE:
                if event.key == pygame.K_ESCAPE: app_state = STATE_MENU
                elif event.key == pygame.K_p: send_msg({"type": "join_room", "room_id": room_code_input.strip(), "as_spectator": False})
                elif event.key == pygame.K_s: send_msg({"type": "join_room", "room_id": room_code_input.strip(), "as_spectator": True})
                elif event.key == pygame.K_BACKSPACE: room_code_input = room_code_input[:-1]
                else:
                    if len(room_code_input) < 12 and event.unicode.isalnum(): room_code_input += event.unicode.upper()
            elif app_state == STATE_WAITING:
                if event.key == pygame.K_ESCAPE: send_msg({"type": "leave_room"}); app_state = STATE_MENU; my_room_id = ""
            elif app_state == STATE_PLAYING:
                if event.key == pygame.K_ESCAPE: send_msg({"type": "leave_room"}); app_state = STATE_MENU; is_spectator, game_over = False, False
                elif not is_spectator:
                    if event.key == pygame.K_SPACE: space_pressed_this_frame = True
                    elif event.key == pygame.K_v: voice_muted = not voice_muted
            

    if time.time() - last_ping_send > 1.0:
        send_msg({"type": "ping", "time": time.time()})
        last_ping_send = time.time()

    screen.fill((30, 30, 30))

    if app_state == STATE_MENU:
        screen.blit(huge_font.render("MAIN MENU", True, (255, 255, 255)), (260, 80))
        # Tambahkan opsi nomor [5] pada loop cetak
        for i, opt in enumerate([
            "[1] Create Public Room", 
            "[2] Create Private Room", 
            "[3] Browse Public Rooms", 
            "[4] Join Private Room",
            "[5] View Match Replay" 
        ]):
            screen.blit(big_font.render(opt, True, (200, 200, 200)), (260, 180 + (i * 55)))
    elif app_state == STATE_WAITING:
        screen.blit(big_font.render("Waiting for opponent...", True, (255, 255, 255)), (270, 230))
        screen.blit(big_font.render(f"Room ID: {my_room_id}", True, (255, 255, 0)), (320, 300))
    elif app_state == STATE_BROWSE:
        screen.blit(big_font.render("Public Rooms", True, (255, 255, 255)), (320, 80))
        for i, r in enumerate(public_rooms):
            color = (255, 255, 0) if i == selected_room_idx else (200, 200, 200)
            screen.blit(font.render(f"[{r['room_id']}] Host: {r['host']} ({r['status']})", True, color), (280, 160 + (i * 30)))
        help_text = font.render("Up/Down to Select | P to join Player | S to join Spectator", True, (100, 100, 100))
        screen.blit(help_text, (400 - help_text.get_width()//2, 500))
    elif app_state == STATE_JOIN_PRIVATE:
        screen.blit(big_font.render("Join Private Room", True, (255, 255, 255)), (270, 80))
        screen.blit(font.render("Masukkan Room ID:", True, (200, 200, 200)), (280, 160))
        pygame.draw.rect(screen, (50, 50, 50), box := pygame.Rect(250, 200, 300, 50))
        pygame.draw.rect(screen, (255, 255, 255), box, 2)
        screen.blit(big_font.render(room_code_input, True, (255, 255, 0)), (box.x + 10, box.y + 5))
        help_text = font.render("Tekan 'P' untuk Main | 'S' untuk Nonton | 'ESC' Batal", True, (100, 100, 100))
        screen.blit(help_text, (400 - help_text.get_width()//2, 280))
        if join_error_msg: screen.blit(font.render(join_error_msg, True, (255, 0, 0)), (400 - font.size(join_error_msg)[0]//2, 330))
    elif app_state == STATE_PLAYING:
        if game_over:
            if disconnect_alert:
                screen.blit(big_font.render("KONEKSI TERPUTUS!", True, (255, 50, 50)), (240, 60))
                alert_surf = font.render(disconnect_alert, True, (200, 200, 200))
                screen.blit(alert_surf, (400 - alert_surf.get_width()//2, 140))
                screen.blit(big_font.render("--- SKOR TERAKHIR ---", True, (100, 200, 255)), (260, 230))
                screen.blit(font.render(f"P1 (Merah) : {score.get('1', 0)} Poin", True, (255, 100, 100)), (300, 290))
                screen.blit(font.render(f"P2 (Biru)  : {score.get('2', 0)} Poin", True, (100, 100, 255)), (300, 330))
                screen.blit(font.render("Tekan ESC untuk kembali ke Main Menu.", True, (150, 150, 150)), (250, 500))
            else:
                screen.blit(big_font.render("TIME'S UP! GAME OVER", True, (255, 215, 0)), (240, 60))
                if score.get('1', 0) > score.get('2', 0): win_text, win_color = "PLAYER 1 (MERAH) MENANG!", (255, 100, 100)
                elif score.get('2', 0) > score.get('1', 0): win_text, win_color = "PLAYER 2 (BIRU) MENANG!", (100, 100, 255)
                else: win_text, win_color = "PERTANDINGAN SERI!", (200, 200, 200)
                txt_surf = huge_font.render(win_text, True, win_color)
                screen.blit(txt_surf, (400 - txt_surf.get_width()//2, 140))
                screen.blit(big_font.render("--- SKOR AKHIR ---", True, (100, 200, 255)), (280, 250))
                sorted_scores = sorted(score.items(), key=lambda item: item[1], reverse=True)
                for idx, (player_id, player_score) in enumerate(sorted_scores):
                    player_name = "P1 (Merah)" if player_id == '1' else "P2 (Biru)"
                    color = (255, 100, 100) if player_id == '1' else (100, 100, 255)
                    screen.blit(font.render(f"{idx + 1}. {player_name} : {player_score} Poin", True, color), (300, 310 + idx * 40))
                screen.blit(font.render("Tekan ESC untuk kembali ke Main Menu.", True, (150, 150, 150)), (250, 500))
        elif is_spectator and not map_data:
            screen.blit(big_font.render("[ SPECTATOR MODE ]", True, (255, 255, 0)), (280, 100))
            screen.blit(big_font.render("Menunggu match dimulai...", True, (200, 200, 200)), (230, 230))
            screen.blit(font.render("Tekan ESC untuk kembali ke Main Menu.", True, (150, 150, 150)), (250, 400))
        else:
            if not is_spectator:
                keys = pygame.key.get_pressed()
                keys_to_send = []
                if keys[pygame.K_w]: keys_to_send.append("MOVE_UP")
                if keys[pygame.K_s]: keys_to_send.append("MOVE_DOWN")
                if keys[pygame.K_a]: keys_to_send.append("MOVE_LEFT")
                if keys[pygame.K_d]: keys_to_send.append("MOVE_RIGHT")
                if keys[pygame.K_q]: keys_to_send.append("ROT_LEFT")
                if keys[pygame.K_e]: keys_to_send.append("ROT_RIGHT")
                if keys_to_send or space_pressed_this_frame:
                    send_msg({"type": "action", "keys": keys_to_send, "shoot": space_pressed_this_frame})

            for obs in map_data:
                pygame.draw.rect(screen, (100, 100, 100), (obs["x"], obs["y"], obs["w"], obs["h"]))
                pygame.draw.rect(screen, (150, 150, 150), (obs["x"], obs["y"], obs["w"], obs["h"]), 2)

            for p_idx_str, p_state in state_cache.items():
                warna = (255, 50, 50) if p_idx_str == "1" else (50, 50, 255)
                px, py = p_state.get("x", -100), p_state.get("y", -100)
                pangle = p_state.get("angle", 0)
                draw_tank_rotated(px, py, pangle, warna, is_me=(p_idx_str == str(my_idx)))
                hp_ratio = max(0, min(100, p_state.get("hp", 100))) / 100
                pygame.draw.rect(screen, (255, 0, 0), (px, py - 12, 40, 6))
                pygame.draw.rect(screen, (0, 255, 0), (px, py - 12, int(40 * hp_ratio), 6))
                hp_txt = font.render(f"HP: {p_state.get('hp', 0)}", True, (0, 255, 0) if p_state.get('hp', 0) > 50 else (255, 0, 0))
                score_txt = font.render(f"Score: {score.get(p_idx_str, 0)}", True, (255, 255, 255))
                screen.blit(hp_txt, (px - 40, py - 45))
                screen.blit(score_txt, (px + 42, py - 45))
            for b in bullet_list_cache:
                pygame.draw.circle(screen, (255, 255, 0), (int(b["x"]), int(b["y"])), 5)
            if is_spectator: screen.blit(big_font.render("[ SPECTATOR MODE ]", True, (255, 255, 0)), (280, 5))
            timer_color = (255, 255, 0) if game_timer > 10 else (255, 50, 50)
            screen.blit(big_font.render(f"Sisa Waktu: {game_timer} Detik", True, timer_color), (280, 40))

    screen.blit(font.render(f"Ping: {ping_ms} ms", True, (0,255,0) if ping_ms < 100 else (255,0,0)), (10, 10))
    screen.blit(font.render(f"ID: {CLIENT_ID[:8]}...", True, (150, 150, 150)), (10, 35))
    if voice_enabled: screen.blit(font.render("Voice: Muted (V)" if voice_muted else "Voice: Active (V)", True, (255,0,0) if voice_muted else (0,255,0)), (10, 60))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()
