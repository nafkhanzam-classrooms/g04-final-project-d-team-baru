import pygame
import json
import sys
import os

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
                data = json.loads(line.strip())
                if data["type"] == "init":
                    map_data = data.get("map", [])
                    usernames = data.get("usernames", usernames)
                elif data["type"] == "frame":
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
    pygame.display.set_caption("TC-TANK Replay Viewer")
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
        
        if playing and current_frame_idx < len(frames) - 1:
            current_frame_idx += max(1, int(playback_speed))
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
        
        # Draw Map
        for obs in map_data:
            pygame.draw.rect(screen, (100, 100, 100), (obs["x"], obs["y"], obs["w"], obs["h"]))
            pygame.draw.rect(screen, (150, 150, 150), (obs["x"], obs["y"], obs["w"], obs["h"]), 2)
            
        # Draw Entities
        if frame["type"] == "frame":
            state = frame.get("state", {})
            for p_idx_str, p_state in state.items():
                color = (255, 50, 50) if p_idx_str == "1" else (50, 50, 255)
                px = p_state.get("x", -100)
                py = p_state.get("y", -100)
                pangle = p_state.get("angle", "UP")
                
                rect = pygame.Rect(px, py, 40, 40)
                pygame.draw.rect(screen, color, rect)
                
                barrel_length = 25
                barrel_width = 8
                cx, cy = px + 20, py + 20
                if pangle == "UP":
                    pygame.draw.rect(screen, color, (cx - barrel_width//2, py - barrel_length + 10, barrel_width, barrel_length))
                elif pangle == "DOWN":
                    pygame.draw.rect(screen, color, (cx - barrel_width//2, cy, barrel_width, barrel_length))
                elif pangle == "LEFT":
                    pygame.draw.rect(screen, color, (px - barrel_length + 10, cy - barrel_width//2, barrel_length, barrel_width))
                elif pangle == "RIGHT":
                    pygame.draw.rect(screen, color, (cx, cy - barrel_width//2, barrel_length, barrel_width))
                    
                hp = p_state.get("hp", 100)
                hp_ratio = max(0, min(100, hp)) / 100
                pygame.draw.rect(screen, (255, 0, 0), (px, py - 12, 40, 6))
                pygame.draw.rect(screen, (0, 255, 0), (px, py - 12, int(40 * hp_ratio), 6))
                
                for b in p_state.get("bullets", []):
                    pygame.draw.circle(screen, (255, 255, 0), (int(b["x"]), int(b["y"])), 4)
                    
            score = frame.get("score", {"1":0, "2":0})
            rnd = frame.get("round", 1)
            
            round_text = big_font.render(f"Round {rnd}/5", True, (255, 255, 255))
            score_text = big_font.render(f"{usernames['1']} (Red) {score['1']} - {score['2']} {usernames['2']} (Blue)", True, (200, 200, 200))
            screen.blit(round_text, (400 - round_text.get_width()//2, 10))
            screen.blit(score_text, (400 - score_text.get_width()//2, 50))
            
        status = "PLAYING" if playing else "PAUSED"
        ui_text = font.render(f"[{status}] Speed: {playback_speed}x | Space: Play/Pause | L/R: Seek | U/D: Speed", True, (255, 255, 0))
        screen.blit(ui_text, (10, 560))
        
        progress = current_frame_idx / max(1, len(frames)-1)
        pygame.draw.rect(screen, (100, 100, 100), (0, 590, 800, 10))
        pygame.draw.rect(screen, (0, 255, 0), (0, 590, int(800 * progress), 10))
        
        pygame.display.flip()
        
        if playback_speed < 1.0:
            clock.tick(int(60 * playback_speed))
        else:
            clock.tick(60)
            
    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
