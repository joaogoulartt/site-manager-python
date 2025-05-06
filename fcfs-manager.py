import requests
import threading
import queue
import time
import os
import logging

LOG_FILENAME = "logs/fcgs-manager.log"

logging.basicConfig(
    filename=LOG_FILENAME,
    filemode="w",
    level=logging.INFO,
    format="%(asctime)s - %(threadName)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class SiteManager:
    def __init__(self, sites):
        self.sites = sites
        self.results = queue.Queue()
        self.lock = threading.Lock()
        self.status_dict = {}
        self.last_update = 0

        # Estrutura para armazenar dados de tempo para médias
        self.timing_data = {
            "Success": {"count": 0, "total_time": 0.0},  # Para 2xx
            "Warning": {"count": 0, "total_time": 0.0},  # Para 4xx com resposta
            "Error": {"count": 0, "total_time": 0.0},  # Para 5xx com resposta
        }

        for site in self.sites:
            self.status_dict[site] = {
                "status": "Aguardando 1ª checagem...",
                "message": "",
            }
        logging.info(f"SiteManager inicializado com {len(sites)} sites.")
        print(f"TERMINAL: SiteManager inicializado com {len(sites)} sites.")

    def check_status_thread_target(self, site):
        thread_name = threading.current_thread().name
        logging.info(f"[{thread_name}] Iniciando checagem para o site: {site}")

        status_code_or_custom = "Erro Desconhecido"
        message = "Não foi possível obter o status."
        numeric_elapsed_time = None  # Tempo de resposta para cálculo da média

        try:
            response = requests.get(site, timeout=10)
            status_code_or_custom = response.status_code
            numeric_elapsed_time = (
                response.elapsed.total_seconds()
            )  # Captura o tempo aqui

            if 200 <= status_code_or_custom < 300:
                if "uuidtools.com/api/generate/" in site:
                    try:
                        uuid_content = response.content.decode()
                    except UnicodeDecodeError:
                        uuid_content = str(response.content)
                    message = (
                        f"Online (UUID: {uuid_content}) - {numeric_elapsed_time:.2f}s"
                    )
                else:
                    message = f"Online - {numeric_elapsed_time:.2f}s"
            elif status_code_or_custom == 404:
                message = f"Página não encontrada - {numeric_elapsed_time:.2f}s"
            elif 400 <= status_code_or_custom < 500:
                message = f"Erro do Cliente ({status_code_or_custom}) - {numeric_elapsed_time:.2f}s"
            elif 500 <= status_code_or_custom < 600:
                message = f"Erro do Servidor ({status_code_or_custom}) - {numeric_elapsed_time:.2f}s"
            else:
                message = f"Status desconhecido ({status_code_or_custom}) - {numeric_elapsed_time:.2f}s"

        except requests.exceptions.Timeout:
            status_code_or_custom = -2  # Nosso código customizado para Timeout
            message = "Timeout na conexão"
            # numeric_elapsed_time permanece None (ou poderia ser o valor do timeout, ex: 10.0)
            logging.warning(f"[{thread_name}] Timeout checando site: {site}")
        except requests.exceptions.ConnectionError:
            status_code_or_custom = -1  # Nosso código customizado para Erro de Conexão
            message = "Erro de conexão"
            logging.warning(f"[{thread_name}] Erro de conexão checando site: {site}")
        except requests.exceptions.RequestException as e:
            status_code_or_custom = -3  # Nosso código customizado para outros erros
            message = f"Erro na requisição: {type(e).__name__}"
            logging.error(f"[{thread_name}] RequestException para o site {site}: {e}")

        logging.info(
            f"[{thread_name}] Checagem concluída para {site}: Status {status_code_or_custom}, Mensagem: {message}"
        )

        with self.lock:
            # Adiciona numeric_elapsed_time à tupla de resultados
            self.results.put(
                (site, status_code_or_custom, message, numeric_elapsed_time)
            )

    def run_checks(self, screen_update_interval=1, site_recheck_period=10):
        if not self.sites:
            msg = "Nenhum site para checar. Encerrando run_checks."
            print(f"TERMINAL: {msg}")
            logging.info(msg)
            return

        logging.info(
            f"run_checks iniciado. Intervalo tela: {screen_update_interval}s. Rechecagem sites: {site_recheck_period}s."
        )
        print(
            f"TERMINAL: run_checks. Tela: {screen_update_interval}s. Rechecagem: {site_recheck_period}s."
        )

        next_full_recheck_time = time.time()
        active_threads_this_cycle = []

        while True:
            current_time = time.time()
            made_updates_to_status_dict = False

            if current_time >= next_full_recheck_time:
                logging.info(
                    f"--- Iniciando ciclo FCFS {len(self.sites)} sites às {time.strftime('%H:%M:%S')} ---"
                )
                print(
                    f"TERMINAL: --- Novo ciclo FCFS {len(self.sites)} sites às {time.strftime('%H:%M:%S')} ---"
                )

                fcfs_dispatch_queue_for_cycle = queue.Queue()
                for site_url in self.sites:
                    fcfs_dispatch_queue_for_cycle.put(site_url)
                logging.info(f"Todos os {len(self.sites)} sites na fila FCFS.")

                with self.lock:
                    self.results = queue.Queue()
                active_threads_this_cycle.clear()

                while not fcfs_dispatch_queue_for_cycle.empty():
                    try:
                        site_to_check = fcfs_dispatch_queue_for_cycle.get_nowait()
                        logging.info(f"FCFS: Despachando {site_to_check}")

                        site_name_for_thread = (
                            site_to_check.split("//")[-1]
                            .replace(".", "-")
                            .replace(":", "-")[:30]
                        )
                        thread = threading.Thread(
                            target=self.check_status_thread_target,
                            args=(site_to_check,),
                            name=f"Check-{site_name_for_thread}",
                        )
                        active_threads_this_cycle.append(thread)
                        thread.start()
                        fcfs_dispatch_queue_for_cycle.task_done()
                    except queue.Empty:
                        break

                next_full_recheck_time = current_time + site_recheck_period
                logging.info(
                    f"Checagens despachadas. Próximo ciclo ~{time.strftime('%H:%M:%S', time.localtime(next_full_recheck_time))}."
                )

            with self.lock:
                while not self.results.empty():
                    try:
                        site, status_val, message_str, response_time_val = (
                            self.results.get_nowait()
                        )

                        self.status_dict[site] = {
                            "status": status_val,
                            "message": message_str,
                        }
                        made_updates_to_status_dict = True
                        logging.debug(f"Resultado: {site}: {status_val}")

                        # Atualizar dados de tempo para médias
                        if (
                            response_time_val is not None
                        ):  # Apenas se houver tempo de resposta
                            category_for_timing = None
                            if isinstance(status_val, int):
                                if 200 <= status_val < 300:
                                    category_for_timing = "Success"
                                elif 400 <= status_val < 500:
                                    category_for_timing = "Warning"  # 4xx
                                elif 500 <= status_val < 600:
                                    category_for_timing = "Error"  # 5xx

                            if category_for_timing:
                                self.timing_data[category_for_timing]["count"] += 1
                                self.timing_data[category_for_timing][
                                    "total_time"
                                ] += response_time_val

                        self.results.task_done()
                    except queue.Empty:
                        break

            if current_time - self.last_update >= screen_update_interval:
                if made_updates_to_status_dict or self.last_update == 0:
                    self.update_screen()
                    self.last_update = current_time

            time.sleep(0.1)

    def update_screen(self):
        os.system("cls" if os.name == "nt" else "clear")
        print("-" * 70)  # Aumentado para caber mais info
        print("          Site Manager (FCFS - Thread per Check)")
        print("-" * 70)

        if not self.status_dict:
            print("Nenhum site para exibir.")
        else:
            for site, data in self.status_dict.items():
                status_val = data["status"]
                message = data["message"]
                status_str = ""

                if isinstance(status_val, int):
                    if 200 <= status_val < 300:
                        status_str = f"\033[92m{status_val}\033[0m"
                    elif status_val == -1:
                        status_str = f"\033[91mErroConex\033[0m"
                    elif status_val == -2:
                        status_str = f"\033[91mTimeout\033[0m"
                    elif status_val == -3:
                        status_str = f"\033[91mReqError\033[0m"
                    elif 400 <= status_val < 500:
                        status_str = f"\033[93m{status_val}\033[0m"
                    elif 500 <= status_val < 600:
                        status_str = f"\033[91m{status_val}\033[0m"
                    else:
                        status_str = str(status_val)
                else:
                    status_str = str(status_val)

                display_site = site[:38] + "..." if len(site) > 41 else site
                # Ajuste na formatação para dar espaço à mensagem de status
                print(f"- {display_site:<42}: {status_str:<18} ({message})")

        print("-" * 70)
        print("Médias de tempo de resposta HTTP (onde aplicável):")
        for category, data in self.timing_data.items():
            if data["count"] > 0:
                avg_time = data["total_time"] / data["count"]
                print(f"  - {category:<10}: {avg_time:.3f}s ({data['count']} amostras)")
            else:
                print(f"  - {category:<10}: N/A (0 amostras)")
        print("-" * 70)

        print(
            f"Última atualização da tela: {time.strftime('%H:%M:%S', time.localtime(self.last_update if self.last_update else time.time()))}"
        )
        try:
            log_mtime = os.path.getmtime(LOG_FILENAME)
            print(
                f"Última escrita no log:      {time.strftime('%H:%M:%S', time.localtime(log_mtime))}"
            )
        except FileNotFoundError:
            print(
                f"Última escrita no log:      (arquivo '{LOG_FILENAME}' não encontrado)"
            )
        except Exception as e:
            print(f"Última escrita no log:      (erro ao ler: {e})")

        print("Pressione Ctrl+C para sair.")


if __name__ == "__main__":
    logging.info("============= Script SiteManager Iniciado =============")
    print("TERMINAL: ============= Script SiteManager Iniciado =============")

    sites_to_check = [
        "https://www.google.com",
        "https://httpbin.org/delay/1",
        "https://httpbin.org/status/204",
        "https://httpbin.org/status/404",
        "https://httpbin.org/status/403",
        "https://httpbin.org/status/500",
        "https://httpbin.org/status/503",
        "https://nonexistentsite12345.com",
        "https://www.example.com",
        "https://www.uuidtools.com/api/generate/v1",
        "https://www.uuidtools.com/api/generate/v4",
        "https://httpbin.org/delay/3",
        "https://httpbin.org/status/418",
        "http://localhost:12345/test",
    ]

    manager = SiteManager(sites_to_check)

    try:
        manager.run_checks(
            screen_update_interval=1, site_recheck_period=10
        )  # Recheck mais rápido para ver médias mudarem
    except KeyboardInterrupt:
        print("\nTERMINAL: Saindo...")
        logging.info("Execução interrompida pelo usuário (Ctrl+C).")
    except Exception as e:
        logging.exception("Uma exceção não tratada ocorreu no loop principal:")
        print(f"\nTERMINAL: Erro crítico: {e}")
    finally:
        logging.info("============= Script SiteManager Finalizado =============")
        print("TERMINAL: ============= Script SiteManager Finalizado =============")
