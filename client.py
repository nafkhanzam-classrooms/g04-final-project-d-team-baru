import pygame
import socket
import threading
import json
import time
import math
import random

# Inisialisasi Pygame
pygame.init()
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Tank Arena - Multiplayer")
font = pygame.font.SysFont("Arial", 20)
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

        # Mengatur thread untuk mendengarkan kiriman data dari Server
        threading.Thread(target=self.receive_data, daemon=True).start()
        # Mengatur thread untuk cek Ping berkala
        threading.Thread(target=self.ping_loop, daemon=True).start()

    def generate_obstacles(self, seed):
        """Sinkronisasi Arena Acak Menggunakan Seed Yang Sama Dari Server"""
        random.seed(seed)
        self.obstacles = []
        for _ in range(8): # Membuat 8 kotak rintangan acak
            x = random.randint(150, WIDTH - 200)
            y = random.randint(100, HEIGHT - 150)
            self.obstacles.append(pygame.Rect(x, y, 60, 60))

    def ping_loop(self):
        while self.running:
            try:
                ping_msg = json.dumps({"type": "PING", "timestamp": time.time()})
                self.client.send(ping_msg.encode())
                time.sleep(2) # Cek ping setiap 2 detik sekali
            except:
                break

    def receive_data(self):
        while self.running:
            try:
                data = self.client.recv(4096).decode()
                if not data:
                    break
                
                msg = json.loads(data)
                
                if msg["type"] == "INIT":
                    self.role = msg["role"]
                    self.room_id = msg["room_id"]
                    self.generate_obstacles(msg["seed"])
                    
                elif msg["type"] == "PONG":
                    self.ping = int((time.time() - msg["timestamp"]) * 1000)
                    
                elif msg["type"] == "UPDATE":
                    self.game_state = msg
            except:
                print("Terputus dari server!")
                self.running = False
                break

    def draw_tank(self, x, y, angle, color):
        # Menggambar badan Tank berbentuk kotak
        tank_surface = pygame.Surface((40, 40), pygame.SRCALPHA)
        pygame.draw.rect(tank_surface, color, (0, 0, 40, 40))
        # Menggambar moncong senjata tank
        pygame.draw.rect(tank_surface, (50, 50, 50), (20, 15, 25, 10))
        
        # Rotasi tank sesuai sudut kemiringan
        rotated_surface = pygame.transform.rotate(tank_surface, angle)
        new_rect = rotated_surface.get_rect(center=(x, y))
        screen.blit(rotated_surface, new_rect.topleft)

    def run(self):
        while self.running:
            screen.fill((30, 30, 30)) # Background abu-abu gelap
            
            # Event Handler Masukan Keyboard
            keys_pressed = []
            shoot = False
            
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        shoot = True

            keys = pygame.key.get_pressed()
            if keys[pygame.K_w]: keys_pressed.append("MOVE_UP")
            if keys[pygame.K_s]: keys_pressed.append("MOVE_DOWN")
            if keys[pygame.K_a]: keys_pressed.append("MOVE_LEFT")
            if keys[pygame.K_d]: keys_pressed.append("MOVE_RIGHT")
            if keys[pygame.K_q]: keys_pressed.append("ROT_LEFT")
            if keys[pygame.K_e]: keys_pressed.append("ROT_RIGHT")

            # Kirim paket input ke server (Real-time update input)
            if keys_pressed or shoot:
                input_data = {"type": "INPUT", "keys": keys_pressed, "shoot": shoot}
                try:
                    self.client.send(json.dumps(input_data).encode())
                except:
                    break

            # Gambar Objek Rintangan / Arena Map
            for obs in self.obstacles:
                pygame.draw.rect(screen, (100, 100, 100), obs)

            # Gambar Seluruh Komponen Game State dari Server (Game State Synchronization)
            if self.game_state:
                # Render UI Atas (Informasi & Latency Indicator)
                room_txt = font.render(f"Room: {self.room_id} | Role: {self.role}", True, (255, 255, 255))
                ping_txt = font.render(f"Ping: {self.ping} ms", True, (0, 255, 0) if self.ping < 100 else (255, 0, 0))
                timer_txt = font.render(f"Waktu: {self.game_state['timer']}s", True, (255, 255, 0))
                screen.blit(room_txt, (10, 10))
                screen.blit(ping_txt, (700, 10))
                screen.blit(timer_txt, (380, 10))

                # Render Semua Tank Pemain
                for p_role, p_data in self.game_state["players"].items():
                    if not p_data["connected"]:
                        continue # Reconnect Handling visual jika pemain dc
                    
                    color = (0, 0, 255) if p_role == "P1" else (255, 0, 0)
                    self.draw_tank(p_data["x"], p_data["y"], p_data["angle"], color)
                    
                    # Gambar text papan skor & darah di atas Tank masing-masing
                    info_text = font.render(f"HP: {p_data['hp']} | Score: {p_data['score']}", True, (255, 255, 255))
                    screen.blit(info_text, (p_data["x"] - 40, p_data["y"] - 40))

                # Render Semua Peluru yang aktif
                for bullet in self.game_state["bullets"]:
                    pygame.draw.circle(screen, (255, 255, 0), (int(bullet["x"]), int(bullet["y"])), 5)

                # Jika waktu habis (Game over)
                if self.game_state["status"] == "ENDED":
                    end_txt = font.render("PERMAINAN SELESAI!", True, (255, 255, 255))
                    screen.blit(end_txt, (WIDTH // 2 - 100, HEIGHT // 2))

            else:
                # Jika belum menemukan lawan di matchmaking
                wait_txt = font.render("Mencari lawan dalam Matchmaking...", True, (255, 255, 255))
                screen.blit(wait_txt, (WIDTH // 2 - 150, HEIGHT // 2))

            pygame.display.flip()
            clock.tick(30) # Kunci visual client di 30 FPS

        pygame.quit()

if __name__ == "__main__":
    client = TankArenaClient()
    client.run()