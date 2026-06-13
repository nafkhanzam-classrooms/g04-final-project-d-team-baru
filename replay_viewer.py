import pygame
import json
import sys
import os
import math

def draw_tank_rotated(screen, x, y, angle, color_body, is_me=False):
    """Menggambar tank dengan sudut derajat bebas (360 derajat) sesuai gameplay aktif"""
    tank_surf = pygame.Surface((40, 40), pygame.SRCALPHA)
    pygame.draw.rect(tank_surf, color_body, (0, 0, 40, 40))
    pygame.draw.rect(tank_surf, (200, 200, 200), (20, 16, 25, 8)) # Moncong hadap kanan (0 derajat)
    
    # Putar permukaan sesuai sudut derajat dari record frame
    # (Gunakan float/int angle langsung hasil passing data server)
    try:
        angle_val = float(angle)
    except:
        # Antisipasi jika record lama masih menyimpan string arah
        mapping = {"RIGHT": 0, "UP": 90, "LEFT": 180, "DOWN": 270}
        angle_val = mapping.get(str(angle), 0)

    rotated_surf = pygame.transform.rotate(tank_surf, angle_val)
    new_rect = rotated_surf.get_rect(center=(x + 20, y + 20))
    screen.blit(rotated_surf, new_rect.topleft)

def main():
    if len(sys.argv) < 2:
        print("Usage: python replay_viewer.py <path_to_replay.jsonl>")
        sys.exit(1)
        
    replay_file = sys.argv[1]
    if not os.path.exists(replay_file):
        print(f"File not found: {replay_file}")
        sys.exit(1)
        
    frames = []
    map_data = []
    usernames = {"1": "Player 1", "2": "Player 2"}
    
    print("Loading replay...")
    with open(replay_file, "r") as f:
        for line in f:
            try:
                if not line.strip(): continue
                data = json.loads(line.strip())
                if data["type"] == "init":
                    map_data = data.get("map", [])
                    usernames = data.get("usernames", usernames)
                elif data["type"] in ["frame", "update"]:
                    frames.append(data)
                elif data["type"] == "round_reset":
                    frames.append(data)
            except:
                pass
                
    if not frames:
        print("No frames found in replay.")
        sys.exit(1)
        
    print(f"Loaded {len(frames)} frames.")
    
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("TC-TANK Replay Viewer - Smooth Mode")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Arial", 20)
    big_font = pygame.font.SysFont("Arial", 36)
    
    current_frame_idx = 0
    playing = True
    playback_speed = 1.0
    
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    playing = not playing
                elif event.key == pygame.K_RIGHT:
                    current_frame_idx = min(len(frames)-1, current_frame_idx + 60)
                elif event.key == pygame.K_LEFT:
                    current_frame_idx = max(0, current_frame_idx - 60)
                elif event.key == pygame.K_UP:
                    playback_speed = min(4.0, playback_speed * 2)
                elif event.key == pygame.K_DOWN:
                    playback_speed = max(0.25, playback_speed / 2)
                elif event.key == pygame.K_ESCAPE:
                    running = False
        
        # Pengendali Kecepatan Play Frame Dinamis
        if playing and current_frame_idx < len(frames) - 1:
            current_frame_idx += max(1, int(playback_speed))
            if playback_speed < 1.0:
                # Menangani kelambatan frame jika speed di-set 0.25x atau 0.5x
                time.sleep((1 / 60) * (1 - playback_speed))
                
            if current_frame_idx >= len(frames):
                current_frame_idx = len(frames) - 1
                playing = False
                
        frame = frames[current_frame_idx]
        
        if frame["type"] == "round_reset":
            map_data = frame.get("map", map_data)
            if playing and current_frame_idx < len(frames) - 1:
                current_frame_idx += 1
                frame = frames[current_frame_idx]
        
        screen.fill((30, 30, 30))
        
        # 1. Render Block Rintangan Map Kotak
        for obs in map_data:
            pygame.draw.rect(screen, (100, 100, 100), (obs["x"], obs["y"], obs["w"], obs["h"]))
            pygame.draw.rect(screen, (150, 150, 150), (obs["x"], obs["y"], obs["w"], obs["h"]), 2)
            
        # 2. Render Entitas Tank Pemain & Semua Peluru
        # (Mendukung tipe data broadcast 'frame' maupun paket 'update')
        if frame["type"] in ["frame", "update"]:
            state = frame.get("state", {})
            score = frame.get("score", {"1": 0, "2": 0})
            game_timer = frame.get("timer", 60)
            game_over = frame.get("game_over", False)
            
            # Render Tank Unit dengan Rotasi 360 Derajat Sempurna
            for p_idx_str, p_state in state.items():
                color = (255, 50, 50) if p_idx_str == "1" else (50, 50, 255)
                px = p_state.get("x", -100)
                py = p_state.get("y", -100)
                pangle = p_state.get("angle", 0)
                
                # Panggil fungsi rotasi bebas 360 derajat yang disempurnakan
                draw_tank_rotated(screen, px, py, pangle, color)
                
                # Render HP Bar di atas Tank
                hp = p_state.get("hp", 100)
                hp_ratio = max(0, min(100, hp)) / 100
                pygame.draw.rect(screen, (255, 0, 0), (px, py - 12, 40, 6))
                pygame.draw.rect(screen, (0, 255, 0), (px, py - 12, int(40 * hp_ratio), 6))
                
                # Render Teks HP dan Score Tambahan agar mirip lobi bermain
                hp_txt = font.render(f"HP: {hp}", True, (0, 255, 0) if hp > 50 else (255, 50, 50))
                screen.blit(hp_txt, (px - 20, py - 35))
                
            # --- SOLUSI UTAMA: AMBIL DATA BULLETS DARI ROOT FRAME BUKAN DARI P_STATE ---
            bullet_list = frame.get("bullets", [])
            for b in bullet_list:
                pygame.draw.circle(screen, (255, 255, 0), (int(b["x"]), int(b["y"])), 5)
                
            # Render HUD Informasi Skor Pertandingan Atas Layar
            round_text = big_font.render(f"Sisa Waktu: {game_timer}s", True, (255, 255, 0))
            score_text = big_font.render(f"{usernames.get('1', 'P1')} {score.get('1', 0)} - {score.get('2', 0)} {usernames.get('2', 'P2')}", True, (200, 200, 200))
            screen.blit(round_text, (400 - round_text.get_width()//2, 10))
            screen.blit(score_text, (400 - score_text.get_width()//2, 50))
            
            # Tampilkan Overlay "GAME OVER" jika rekaman mendeteksi durasi habis
            if game_over:
                over_txt = big_font.render("PERTANDINGAN SELESAI!", True, (255, 50, 50))
                screen.blit(over_txt, (400 - over_txt.get_width()//2, 300))
            
        # Render Teks Informasi Kendali Kontrol UI Bawah
        status = "PLAYING" if playing else "PAUSED"
        ui_text = font.render(f"[{status}] Speed: {playback_speed}x | Space: Play/Pause | L/R: Seek | U/D: Speed | ESC: Exit", True, (255, 255, 0))
        screen.blit(ui_text, (10, 540))
        
        # Render Progres Bar Alur Berjalannya Replay
        progress = current_frame_idx / max(1, len(frames)-1)
        pygame.draw.rect(screen, (100, 100, 100), (20, 575, 760, 10))
        pygame.draw.rect(screen, (0, 255, 0), (20, 575, int(760 * progress), 10))
        
        pygame.display.flip()
        clock.tick(60) # Jalankan di 60 FPS dasar agar seek L/R terasa instan responsif
            
    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
