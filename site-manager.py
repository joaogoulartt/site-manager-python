import requests
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
import time
import os
import datetime

LOG_DIR = "logs"
SUCCESS_LOG_FILE = os.path.join(LOG_DIR, "success_log.txt")
WARNING_LOG_FILE = os.path.join(LOG_DIR, "warning_log.txt")
ERROR_LOG_FILE = os.path.join(LOG_DIR, "error_log.txt")
GENERAL_LOG_FILE = os.path.join(LOG_DIR, "general_log.txt")

PRIORITY_SCHEDULER_INTERVAL = 5
UPDATE_INTERVAL = 1

class LogEntry:
    """Representa uma entrada de log com detalhes relevantes."""
    def __init__(self, site, status, message, arrival_time):
        self.site = site
        self.status = status
        self.message = message
        self.arrival_time = arrival_time

        self.priority_process_time = None

    def __str__(self):
        """Representação em string para logging."""
        arrival_str = self.arrival_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        priority_process_str = self.priority_process_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if self.priority_process_time else "N/A"
        return f"Arrival: {arrival_str} | Priority_Process: {priority_process_str} | Status: {self.status} | Site: {self.site} | Message: {self.message}"

    def to_file_str(self):
        """Representação em string especificamente para escrita nos arquivos de status."""
        arrival_timestamp = self.arrival_time.timestamp()
        return f"{arrival_timestamp}|{self.status}|{self.site}|{self.message}"

    @classmethod
    def from_file_str(cls, line):
        """Cria um objeto LogEntry a partir de uma linha lida de um arquivo de status."""
        try:
            parts = line.strip().split('|', 3)
            if len(parts) == 4:
                arrival_timestamp, status_str, site, message = parts
                arrival_time = datetime.datetime.fromtimestamp(float(arrival_timestamp))
                try:
                    status = int(status_str)
                except ValueError:
                    status = status_str
                return cls(site, status, message, arrival_time)
        except Exception as e:
            print(f"Erro ao parsear linha de log: {line.strip()} - {e}")
        return None


class SiteManager:
    def __init__(self, sites):
        self.sites = sites
        self.status_dict = {site: {"status": "Pending", "message": ""} for site in sites}
        self.last_update = 0

        self.success_queue = queue.Queue()
        self.warning_queue = queue.Queue()
        self.error_queue = queue.Queue()

        self.success_lock = threading.Lock()
        self.warning_lock = threading.Lock()
        self.error_lock = threading.Lock()
        self.general_lock = threading.Lock()

        self._stop_event = threading.Event()

        self.current_run_stats = {
            "success": {"total_wait": 0, "count": 0},
            "warning": {"total_wait": 0, "count": 0},
            "error": {"total_wait": 0, "count": 0},
        }
        self.avg_waiting_times_last_cycle = {"success": 0, "warning": 0, "error": 0}

        self.overall_stats = {
            "success": {"total_wait": 0, "count": 0},
            "warning": {"total_wait": 0, "count": 0},
            "error": {"total_wait": 0, "count": 0},
        }
        self.avg_waiting_times_overall = {"success": 0, "warning": 0, "error": 0}

        self._setup_logging()

    def _setup_logging(self):
        """Cria o diretório de log e limpa os arquivos de log."""
        os.makedirs(LOG_DIR, exist_ok=True)
        log_files_to_clear = [
            SUCCESS_LOG_FILE,
            WARNING_LOG_FILE,
            ERROR_LOG_FILE,
            GENERAL_LOG_FILE
        ]
        for log_file in log_files_to_clear:
            try:
                with open(log_file, 'w') as f:
                    f.write("")
                print(f"Arquivo de log limpo: {log_file}")
            except IOError as e:
                print(f"Erro ao limpar arquivo {log_file}: {e}")


    def check_status(self, site):
        """Verifica o status de um único site e coloca o resultado na fila apropriada."""
        if self._stop_event.is_set():
            return

        arrival_time = datetime.datetime.now()
        status_code = None
        message = ""

        try:
            self.status_dict[site] = {"status": "Checking...", "message": ""}
            response = requests.get(site, timeout=10)
            status_code = response.status_code
            elapsed_time = response.elapsed.total_seconds()

            if 200 <= status_code < 300:
                message = f"Online - {elapsed_time:.3f}s"
                log_entry = LogEntry(site, status_code, message, arrival_time)
                self.success_queue.put(log_entry)
            elif 400 <= status_code < 500:
                message = f"Client Error ({status_code}) - {elapsed_time:.3f}s"
                log_entry = LogEntry(site, status_code, message, arrival_time)
                self.warning_queue.put(log_entry)
            elif 500 <= status_code < 600:
                message = f"Server Error ({status_code}) - {elapsed_time:.3f}s"
                log_entry = LogEntry(site, status_code, message, arrival_time)
                self.error_queue.put(log_entry)
            else:
                message = f"Unknown status ({status_code}) - {elapsed_time:.3f}s"
                log_entry = LogEntry(site, status_code, message, arrival_time)
                self.warning_queue.put(log_entry)

        except requests.exceptions.Timeout:
            status_code = "Timeout"
            message = "Connection Timeout"
            log_entry = LogEntry(site, status_code, message, arrival_time)
            self.error_queue.put(log_entry)
        except requests.exceptions.ConnectionError:
            status_code = "Conn Error"
            message = "Connection Error"
            log_entry = LogEntry(site, status_code, message, arrival_time)
            self.error_queue.put(log_entry)
        except requests.exceptions.RequestException as e:
            status_code = "Req Error"
            message = f"Request Error: {type(e).__name__}"
            log_entry = LogEntry(site, status_code, message, arrival_time)
            self.error_queue.put(log_entry)
        finally:
            if status_code is not None:
                 self.status_dict[site] = {"status": status_code, "message": message}
            else:
                 self.status_dict[site] = {"status": "Failed", "message": "Check Failed"}


    def _fcfs_log_writer(self, log_queue, log_file, file_lock, category_name):
        """
        Função alvo para as threads escritoras de log FCFS.
        Lê de uma fila e escreve em um arquivo de log usando um lock.
        """
        print(f"Iniciando thread escritora FCFS para: {category_name}")
        while not self._stop_event.is_set():
            try:
                log_entry = log_queue.get(timeout=0.5)

                log_entry.fcfs_write_time = datetime.datetime.now()

                with file_lock:
                    try:
                        with open(log_file, 'a') as f:
                            f.write(log_entry.to_file_str() + '\n')
                    except IOError as e:
                        print(f"Erro ao escrever em {log_file}: {e}")

                log_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                print(f"Erro na thread escritora FCFS ({category_name}): {e}")

        print(f"Parando thread escritora FCFS para: {category_name}")


    def _priority_scheduler(self):
        """
        Função alvo para a thread do agendador prioritário.
        Periodicamente lê logs dos arquivos de status baseado em prioridade,
        calcula tempo de espera, e escreve no log geral.
        """
        while not self._stop_event.is_set():
            try:
                self._stop_event.wait(PRIORITY_SCHEDULER_INTERVAL)
                if self._stop_event.is_set(): break


                processed_logs = []

                self.current_run_stats = {
                    "success": {"total_wait": 0, "count": 0},
                    "warning": {"total_wait": 0, "count": 0},
                    "error": {"total_wait": 0, "count": 0},
                }

                log_sources = [
                    ("error", ERROR_LOG_FILE, self.error_lock),
                    ("warning", WARNING_LOG_FILE, self.warning_lock),
                    ("success", SUCCESS_LOG_FILE, self.success_lock),
                ]

                for category, log_file, file_lock in log_sources:
                    lines_to_keep = []
                    processed_category_logs = []

                    with file_lock:
                        try:
                            if not os.path.exists(log_file):
                                continue

                            with open(log_file, 'r+') as f:
                                lines = f.readlines()
                                f.seek(0)
                                f.truncate()

                                processing_time = datetime.datetime.now()

                                for line in lines:
                                    log_entry = LogEntry.from_file_str(line)
                                    if log_entry:
                                        log_entry.priority_process_time = processing_time
                                        wait_time = (log_entry.priority_process_time - log_entry.arrival_time).total_seconds()

                                        self.current_run_stats[category]["total_wait"] += wait_time
                                        self.current_run_stats[category]["count"] += 1

                                        self.overall_stats[category]["total_wait"] += wait_time
                                        self.overall_stats[category]["count"] += 1

                                        processed_category_logs.append(log_entry)
                                    else:
                                        lines_to_keep.append(line)

                        except IOError as e:
                            print(f"Erro de I/O ao acessar {log_file}: {e}")
                        except Exception as e:
                            print(f"Erro inesperado ao processar {log_file}: {e}")

                    processed_logs.extend(processed_category_logs)
                   

                if processed_logs:
                    with self.general_lock:
                        try:
                            with open(GENERAL_LOG_FILE, 'a') as f:
                                for log in processed_logs:
                                    f.write(str(log) + '\n')
                        except IOError as e:
                            print(f"Erro ao escrever em {GENERAL_LOG_FILE}: {e}")

                for category in self.avg_waiting_times_last_cycle:
                    count = self.current_run_stats[category]["count"]
                    total_wait = self.current_run_stats[category]["total_wait"]
                    if count > 0:
                        self.avg_waiting_times_last_cycle[category] = total_wait / count
                    else:
                        self.avg_waiting_times_last_cycle[category] = 0

                for category in self.avg_waiting_times_overall:
                    count = self.overall_stats[category]["count"]
                    total_wait = self.overall_stats[category]["total_wait"]
                    if count > 0:
                        self.avg_waiting_times_overall[category] = total_wait / count
                    else:
                        self.avg_waiting_times_overall[category] = 0

            except Exception as e:
                print(f"Erro no loop do Agendador Prioritário: {e}")
                time.sleep(1)



    def run_checks(self, num_threads=4):
        """
        Inicia o processo de monitoramento, incluindo escritores FCFS e Agendador Prioritário.
        """
        self.threads = []

        writer_threads_config = [
            (self.success_queue, SUCCESS_LOG_FILE, self.success_lock, "Success"),
            (self.warning_queue, WARNING_LOG_FILE, self.warning_lock, "Warning"),
            (self.error_queue, ERROR_LOG_FILE, self.error_lock, "Error"),
        ]
        for q, f, lock, name in writer_threads_config:
            thread = threading.Thread(target=self._fcfs_log_writer, args=(q, f, lock, name), daemon=True)
            thread.start()
            self.threads.append(thread)

        scheduler_thread = threading.Thread(target=self._priority_scheduler, daemon=True)
        scheduler_thread.start()
        self.threads.append(scheduler_thread)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            print(f"Iniciando verificações de site com {num_threads} threads worker...")
            while not self._stop_event.is_set():
                futures = [executor.submit(self.check_status, site) for site in self.sites]

                wait_interval = 2.0
                self._stop_event.wait(wait_interval)

                current_time = time.time()
                if current_time - self.last_update >= UPDATE_INTERVAL:
                    self.update_screen()
                    self.last_update = current_time

    def stop(self):
        """Sinaliza a todas as threads para pararem graciosamente."""
        print("\nEnviando sinal de parada para as threads...")
        self._stop_event.set()


    def update_screen(self):
        """Limpa a tela e exibe os status atuais dos sites e os tempos médios de espera."""
        os.system("cls" if os.name == "nt" else "clear")
        print("-" * 70)
        print("          Monitor de Site com Simulação de Log")
        print("-" * 70)
        print(f"Diretório de Logs: {LOG_DIR}")
        print("-" * 70)

        print("Status dos Sites:")
        for site, data in self.status_dict.items():
            status = data["status"]
            message = data["message"]

            if isinstance(status, int) and 200 <= status < 300:
                status_str = f"\033[92m{status}\033[0m"
            elif status in ["Timeout", "Conn Error", "Req Error"] or (isinstance(status, int) and 500 <= status < 600):
                status_str = f"\033[91m{status}\033[0m"
            elif isinstance(status, int) and 400 <= status < 500:
                status_str = f"\033[93m{status}\033[0m"
            else:
                status_str = f"\033[94m{status}\033[0m"

            print(f"- {site:<35}: {status_str:<18} ({message})")

        print("-" * 70)

        print("Tempo Médio de Espera (Agendamento Prioritário - Último Ciclo):")
        print(f"- Erros   : {self.avg_waiting_times_last_cycle['error']:.3f}s (Processados no ciclo: {self.current_run_stats['error']['count']})")
        print(f"- Avisos  : {self.avg_waiting_times_last_cycle['warning']:.3f}s (Processados no ciclo: {self.current_run_stats['warning']['count']})")
        print(f"- Sucesso : {self.avg_waiting_times_last_cycle['success']:.3f}s (Processados no ciclo: {self.current_run_stats['success']['count']})")

        print("-" * 70)

        print("Tempo Médio de Espera (Agendamento Prioritário - Geral):")
        print(f"- Erros   : {self.avg_waiting_times_overall['error']:.3f}s (Total processado: {self.overall_stats['error']['count']})")
        print(f"- Avisos  : {self.avg_waiting_times_overall['warning']:.3f}s (Total processado: {self.overall_stats['warning']['count']})")
        print(f"- Sucesso : {self.avg_waiting_times_overall['success']:.3f}s (Total processado: {self.overall_stats['success']['count']})")

        print("-" * 70)
        print(f"Última atualização da tela: {time.strftime('%H:%M:%S')}")
        print("Pressione Ctrl+C para sair.")
        print("-" * 70)


if __name__ == "__main__":
    sites_to_check = [
        "https://www.google.com",
        "https://httpbin.org/delay/1",
        "https://httpbin.org/status/404",
        "https://httpbin.org/status/418",
        "https://httpbin.org/status/500",
        "https://httpbin.org/delay/3",
        "https://httpbin.org/status/503",
        "https://httpbin.org/status/401",
        "https://httpbin.org/status/405",
        "https://invalid-domain-that-does-not-exist-blah.com",
        "https://httpbin.org/delay/0.5",
        "https://httpbin.org/status/403",
        "http://httpbin.org/delay/4"
    ]

    manager = SiteManager(sites_to_check)

    try:
        num_workers = len(sites_to_check)
        manager.run_checks(num_threads=num_workers)
    except KeyboardInterrupt:
        print("\nCtrl+C detectado. Iniciando desligamento...")
        manager.stop()
        print("Saindo.")
    except Exception as e:
        print(f"\nOcorreu um erro inesperado: {e}")
        manager.stop()

