import pygame
import socket
import threading
import json
import time
import random

pygame.init()
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Tank Arena - NRP 5025241190")
font = pygame.font.SysFont("Arial", 20)
large_font = pygame.font.SysFont("Arial", 40, bold=True)
clock = pygame.time.Clock()

HOST = '127.0.0.1'
PORT = 5555

class TankArenaClient:
    def __init__(self):
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client.connect((HOST, PORT))
        
        self.role = None
        self.room_id = None
        self.game_state = None
        self.obstacles = []
        self.ping = 0
        self.running = True
        self.chat_logs = []

        threading.Thread(target=self.receive_data, daemon=True).start()
        threading.Thread(target=self.ping_loop, daemon=True).start()

    def generate_obstacles(self, seed):
        random.seed(seed)
        self.obstacles = []
        for _ in range(8):
            x = random.randint(150, WIDTH - 200)
            y = random.randint(100, HEIGHT - 150)
            self.obstacles.append(pygame.Rect(x, y, 60, 60))

    def ping_loop(self):
        while self.running:
            try:
                ping_msg = json.dumps({"type": "PING", "timestamp": time.time()})
                self.client.send((ping_msg + "\n").encode())
                time.sleep(2)
            except:
                break

    def receive_data(self):
        while self.running:
            try:
                data = self.client.recv(4096).decode()
                if not data: break
                messages = data.strip().split('\n')
                for message in messages:
                    if not message: continue
                    msg = json.loads(message)
                    
                    if msg["type"] == "INIT":
                        self.role = msg["role"]
                        self.room_id = msg["room_id"]
                        self.generate_obstacles(msg["seed"])
                    elif msg["type"] == "PONG":
                        self.ping = int((time.time() - msg["timestamp"]) * 1000)
                    elif msg["type"] == "UPDATE":
                        self.game_state = msg
                    elif msg["type"] == "CHAT_MSG":
                        self.chat_logs.append(msg["text"])
                        if len(self.chat_logs) > 3: self.chat_logs.pop(0)
            except:
                print("Terputus dari server!")
                self.running = False
                break

    def draw_tank(self, x, y, angle, color):
        tank_surface = pygame.Surface((40, 40), pygame.SRCALPHA)
        pygame.draw.rect(tank_surface, color, (0, 0, 40, 40))
        pygame.draw.rect(tank_surface, (50, 50, 50), (20, 15, 25, 10))
        
        rotated_surface = pygame.transform.rotate(tank_surface, angle)
        new_rect = rotated_surface.get_rect(center=(x, y))
        screen.blit(rotated_surface, new_rect.topleft)

    def run(self):
        shoot_cooldown = 0
        while self.running:
            screen.fill((40, 45, 50))
            keys_pressed = []
            shoot = False
            
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE and shoot_cooldown == 0:
                        shoot = True
                        shoot_cooldown = 5 # Hindari spam tembak
                    elif event.key == pygame.K_c: # Bonus: Simple Chat Communication
                        chat_msg = {"type": "CHAT", "text": "GGWP!"}
                        self.client.send((json.dumps(chat_msg) + "\n").encode())

            if shoot_cooldown > 0: shoot_cooldown -= 1

            keys = pygame.key.get_pressed()
            if self.role != "SPECTATOR":
                if keys[pygame.K_w]: keys_pressed.append("MOVE_UP")
                if keys[pygame.K_s]: keys_pressed.append("MOVE_DOWN")
                if keys[pygame.K_a]: keys_pressed.append("MOVE_LEFT")
                if keys[pygame.K_d]: keys_pressed.append("MOVE_RIGHT")
                if keys[pygame.K_q]: keys_pressed.append("ROT_LEFT")
                if keys[pygame.K_e]: keys_pressed.append("ROT_RIGHT")

                if keys_pressed or shoot:
                    input_data = {"type": "INPUT", "keys": keys_pressed, "shoot": shoot}
                    try: self.client.send((json.dumps(input_data) + "\n").encode())
                    except: break

            # Gambar Obstacles
            for obs in self.obstacles:
                pygame.draw.rect(screen, (139, 69, 19), obs) # Warna kotak kayu

            if self.game_state:
                # UI Status
                room_txt = font.render(f"Room: {self.room_id} | Role: {self.role}", True, (255, 255, 255))
                ping_txt = font.render(f"Ping: {self.ping} ms", True, (0, 255, 0) if self.ping < 100 else (255, 0, 0))
                timer_txt = font.render(f"Waktu: {self.game_state['timer']}s", True, (255, 255, 0))
                
                screen.blit(room_txt, (10, 10))
                screen.blit(ping_txt, (WIDTH - 120, 10))
                screen.blit(timer_txt, (WIDTH // 2 - 40, 10))

                # Render Tanks & Bullets
                for p_role, p_data in self.game_state["players"].items():
                    if not p_data["connected"]: continue
                    color = (50, 150, 255) if p_role == "P1" else (255, 100, 100)
                    self.draw_tank(p_data["x"], p_data["y"], p_data["angle"], color)
                    
                    hp_txt = font.render(f"HP: {p_data['hp']}", True, (0, 255, 0) if p_data['hp'] > 50 else (255, 0, 0))
                    score_txt = font.render(f"Score: {p_data['score']}", True, (255, 255, 255))
                    screen.blit(hp_txt, (p_data["x"] - 30, p_data["y"] - 45))
                    screen.blit(score_txt, (p_data["x"] - 30, p_data["y"] + 25))

                for bullet in self.game_state["bullets"]:
                    pygame.draw.circle(screen, (255, 255, 0), (int(bullet["x"]), int(bullet["y"])), 5)

                # Render Komunikasi Chat (Kiri Bawah)
                for i, log in enumerate(self.chat_logs):
                    chat_txt = font.render(log, True, (200, 200, 200))
                    screen.blit(chat_txt, (10, HEIGHT - 80 + (i * 20)))

                # Kondisi Akhir (Menampilkan Ranking)
                if self.game_state["status"] == "ENDED":
                    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                    overlay.fill((0, 0, 0, 180))
                    screen.blit(overlay, (0, 0))
                    
                    end_txt = large_font.render("MATCH SELESAI!", True, (255, 215, 0))
                    screen.blit(end_txt, (WIDTH // 2 - 150, HEIGHT // 3))
                    
                    # Hitung Pemenang
                    p1_score = self.game_state["players"]["P1"]["score"]
                    p2_score = self.game_state["players"].get("P2", {}).get("score", 0)
                    
                    rank_txt = font.render(f"P1 Score: {p1_score} | P2 Score: {p2_score}", True, (255, 255, 255))
                    screen.blit(rank_txt, (WIDTH // 2 - 120, HEIGHT // 2))

            else:
                wait_txt = font.render("Menunggu Matchmaking...", True, (200, 200, 200))
                screen.blit(wait_txt, (WIDTH // 2 - 120, HEIGHT // 2))

            pygame.display.flip()
            clock.tick(30)

        pygame.quit()

if __name__ == "__main__":
    client = TankArenaClient()
    client.run()
