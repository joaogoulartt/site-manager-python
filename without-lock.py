import requests
import queue
from concurrent.futures import ThreadPoolExecutor
import time
import os
import threading

CUSTOM_UNSAFE_LOG_FILENAME = "logs/without_lock.txt"
CUSTOM_LOG_DIR = os.path.dirname(CUSTOM_UNSAFE_LOG_FILENAME)
if CUSTOM_LOG_DIR and not os.path.exists(CUSTOM_LOG_DIR):
    os.makedirs(CUSTOM_LOG_DIR, exist_ok=True)
if os.path.exists(CUSTOM_UNSAFE_LOG_FILENAME):
    os.remove(CUSTOM_UNSAFE_LOG_FILENAME)


class SiteManager:
    def __init__(self, sites):
        self.sites = sites
        self.results = queue.Queue()
        self.status_dict = {}
        self.last_update = 0
        print(
            f"TERMINAL: SiteManager (No Lock Version, No Logging Module) inicializado com {len(sites)} sites."
        )

    def check_status(self, site):
        thread_name = threading.current_thread().name

        try:
            with open(CUSTOM_UNSAFE_LOG_FILENAME, "a", encoding="utf-8") as f_unsafe:
                f_unsafe.write(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S,%03d')} - [{thread_name}] - INICIANDO Checagem: {site}\n"
                )
        except Exception as e_write:
            print(
                f"TERMINAL ERRO DE ESCRITA (INÍCIO CUSTOM LOG): [{thread_name}] para {site}: {e_write}"
            )

        status_val = None
        message = "Status não determinado"
        http_response_time_info = ""

        try:
            response = requests.get(site, timeout=5)
            status_val = response.status_code
            elapsed_http_time = response.elapsed.total_seconds()
            http_response_time_info = f"{elapsed_http_time:.2f}s"

            if 200 <= status_val < 300:
                if site == "https://www.uuidtools.com/api/generate/v2":
                    message = f"Online (UUID: {response.content.decode()}) - {http_response_time_info}"
                elif site == "https://www.uuidtools.com/api/generate/v4":
                    message = f"Online (UUID: {response.content.decode()}) - {http_response_time_info}"
                else:
                    message = f"Online - {http_response_time_info}"
            elif status_val == 404:
                message = f"Page not found - {http_response_time_info}"
            elif 400 <= status_val < 500:
                message = f"Client Error ({status_val}) - {http_response_time_info}"
            elif 500 <= status_val < 600:
                message = f"Server Error ({status_val}) - {http_response_time_info}"
            else:
                message = f"Unknown status ({status_val}) - {http_response_time_info}"

        except requests.exceptions.Timeout:
            message = "Connection Timeout"
            status_val = -2
        except requests.exceptions.ConnectionError as e:
            message = "Connection Error"
            status_val = -1
        except requests.exceptions.RequestException as e:
            message = f"Request Error: {type(e).__name__}"
            status_val = -3
        except Exception as e:
            message = f"Erro inesperado: {type(e).__name__}"
            status_val = -4
            print(
                f"TERMINAL ERRO INESPERADO: [{thread_name}] em check_status para {site}: {e}"
            )

        try:
            with open(CUSTOM_UNSAFE_LOG_FILENAME, "a", encoding="utf-8") as f_unsafe:
                f_unsafe.write(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S,%03d')} - [{thread_name}] - CONCLUÍDO {site} - "
                )
                f_unsafe.write(f"Status: {status_val} - Mensagem: {message}\n")
        except Exception as e_write:
            print(
                f"TERMINAL ERRO DE ESCRITA (FIM CUSTOM LOG): [{thread_name}] para {site}: {e_write}"
            )

        self.results.put((site, status_val, message))

    def run_checks(self, num_threads=4, update_interval=1):
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            for site in self.sites:
                self.status_dict[site] = {"status": "Checking...", "message": ""}

            while True:
                self.results = queue.Queue()

                for site in self.sites:
                    executor.submit(self.check_status, site)

                time.sleep(0.5)

                results_this_cycle = 0
                while not self.results.empty():
                    try:
                        site, status_val, message = self.results.get_nowait()
                        self.status_dict[site] = {
                            "status": status_val,
                            "message": message,
                        }
                        results_this_cycle += 1
                        self.results.task_done()
                    except queue.Empty:
                        break

                if time.time() - self.last_update >= update_interval:
                    self.update_screen()
                    self.last_update = time.time()

                time.sleep(update_interval / 2 if update_interval > 0.2 else 0.1)

    def update_screen(self):
        os.system("cls" if os.name == "nt" else "clear")
        print("-" * 40)
        print("          Site Manager (SEM LOCKS + UNSAFE WRITE)")
        print("-" * 40)

        for site, data in self.status_dict.items():
            status = data["status"]
            message = data["message"]
            status_str = str(status)
            if isinstance(status, int) and 200 <= status < 300:
                status_str = f"\033[92m{status}\033[0m"
            elif status == -1 or status == -2 or status == -3 or status == -4:
                status_str = f"\033[91mError ({status})\033[0m"
            elif isinstance(status, int) and 400 <= status < 600:
                status_str = f"\033[93m{status}\033[0m"

            print(f"- {site:<30}: {status_str:<15} ({message})")

        print("-" * 40)
        print(f"Last update: {time.strftime('%H:%M:%S')}")
        print("Press Ctrl+C to exit.")


if __name__ == "__main__":
    print(
        "TERMINAL: ============= Script SiteManager (No Lock, No Logging Module) Iniciado ============="
    )

    sites_to_check = [
        "https://www.google.com",
        "https://httpbin.org/delay/1",
        "https://httpbin.org/status/200",
        "https://www.bing.com",
        "https://httpbin.org/delay/0.5",
        "https://httpbin.org/status/201",
        "https://www.duckduckgo.com",
        "https://httpbin.org/delay/1.5",
        "https://httpbin.org/status/202",
        "https://www.yahoo.com",
        "https://httpbin.org/delay/0.2",
        "https://httpbin.org/status/203",
        "https://www.wikipedia.org",
        "https://httpbin.org/delay/0.7",
        "https://httpbin.org/status/204",
        "https://www.amazon.com",
        "https://httpbin.org/delay/1.2",
        "https://httpbin.org/status/205",
        "https://www.ebay.com",
        "https://httpbin.org/delay/0.3",
        "https://httpbin.org/status/206",
    ]

    manager = SiteManager(sites_to_check)

    try:
        num_sites = len(sites_to_check)
        manager.run_checks(
            num_threads=num_sites if num_sites > 0 else 4, update_interval=0.5
        )
    except KeyboardInterrupt:
        print("\nSaindo...")
        # logging.info("Execução interrompida pelo usuário (Ctrl+C).") # Removido
    except Exception as e:
        # logging.exception("Uma exceção não tratada ocorreu no loop principal (No Lock + Unsafe Writes):") # Removido
        print(f"\nTERMINAL ERRO CRÍTICO (No Lock, No Logging Module): {e}")
        # Poderia adicionar um traceback manual aqui se desejado:
        # import traceback
        # traceback.print_exc()
    finally:
        # logging.info("============= Script SiteManager (No Lock Version with Unsafe Writes) Finalizado =============") # Removido
        print(
            "TERMINAL: ============= Script SiteManager (No Lock, No Logging Module) Finalizado ============="
        )
