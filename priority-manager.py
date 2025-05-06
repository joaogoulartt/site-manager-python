import requests
import threading
import queue
import time
import os
import logging
import copy

LOG_FILENAME = "logs/priority-manager.log"

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

        self.timing_data = {
            "Success": {"count": 0, "total_time": 0.0},
            "Warning": {"count": 0, "total_time": 0.0},
            "Error": {"count": 0, "total_time": 0.0},
        }
        self.current_cycle_category_timing = {
            "Success": {"count": 0, "total_time": 0.0},
            "Warning": {"count": 0, "total_time": 0.0},
            "Error": {"count": 0, "total_time": 0.0},
        }
        self.last_cycle_category_timing_snapshot = {
            "Success": {"count": 0, "total_time": 0.0},
            "Warning": {"count": 0, "total_time": 0.0},
            "Error": {"count": 0, "total_time": 0.0},
        }
        self.last_cycle_overall_avg_response_time = None
        self.last_cycle_overall_response_count = 0

        for site in self.sites:
            self.status_dict[site] = {
                "status": "Aguardando 1ª checagem...",
                "message": "",
            }
        logging.info(
            f"SiteManager (Priority Scheduling) inicializado com {len(sites)} sites."
        )
        print(
            f"TERMINAL: SiteManager (Priority Scheduling) inicializado com {len(sites)} sites."
        )

    def check_status_thread_target(self, site):
        thread_name = threading.current_thread().name
        logging.info(f"[{thread_name}] Iniciando checagem para o site: {site}")

        t_start_check_process = time.time()

        status_code_or_custom = "Erro Desconhecido"
        message = "Não foi possível obter o status."
        http_response_time_info = ""

        try:
            response = requests.get(site, timeout=10)
            status_code_or_custom = response.status_code
            elapsed_http_time = response.elapsed.total_seconds()
            http_response_time_info = f"{elapsed_http_time:.2f}s HTTP"

            if 200 <= status_code_or_custom < 300:
                if "uuidtools.com/api/generate/" in site:
                    try:
                        uuid_content = response.content.decode()
                    except UnicodeDecodeError:
                        uuid_content = str(response.content)
                    message = (
                        f"Online (UUID: {uuid_content}) - {http_response_time_info}"
                    )
                else:
                    message = f"Online - {http_response_time_info}"
            elif status_code_or_custom == 404:
                message = f"Página não encontrada - {http_response_time_info}"
            elif 400 <= status_code_or_custom < 500:
                message = f"Erro Cliente ({status_code_or_custom}) - {http_response_time_info}"
            elif 500 <= status_code_or_custom < 600:
                message = f"Erro Servidor ({status_code_or_custom}) - {http_response_time_info}"
            else:
                message = (
                    f"Status ({status_code_or_custom}) - {http_response_time_info}"
                )
        except requests.exceptions.Timeout:
            status_code_or_custom = -2
            message = "Timeout na conexão"
            logging.warning(f"[{thread_name}] Timeout: {site}")
        except requests.exceptions.ConnectionError:
            status_code_or_custom = -1
            message = "Erro de conexão"
            logging.warning(f"[{thread_name}] Erro conexão: {site}")
        except requests.exceptions.RequestException as e:
            status_code_or_custom = -3
            message = f"Erro req: {type(e).__name__}"
            logging.error(f"[{thread_name}] ReqException {site}: {e}")

        final_log_message = f"[{thread_name}] Concluído {site}: Status {status_code_or_custom}, Msg: {message}"
        logging.info(final_log_message)

        t_end_log_process = time.time()

        duration_proc_and_log = t_end_log_process - t_start_check_process

        with self.lock:
            self.results.put(
                (site, status_code_or_custom, message, duration_proc_and_log)
            )

    def run_checks(self, screen_update_interval=1, site_recheck_period=10):
        if not self.sites:
            msg = "Nenhum site para checar. Encerrando run_checks."
            print(f"TERMINAL: {msg}")
            logging.info(msg)
            return

        logging.info(
            f"run_checks (Priority) iniciado. Tela: {screen_update_interval}s. Rechecagem: {site_recheck_period}s."
        )
        print(
            f"TERMINAL: run_checks (Priority). Tela: {screen_update_interval}s. Rechecagem: {site_recheck_period}s."
        )

        next_full_recheck_time = time.time()
        active_threads_this_cycle = []

        while True:
            current_time = time.time()
            made_updates_to_status_dict = False

            if current_time >= next_full_recheck_time:
                overall_total_duration_completed_cycle = 0
                overall_item_count_completed_cycle = 0
                for category_data in self.current_cycle_category_timing.values():
                    overall_total_duration_completed_cycle += category_data[
                        "total_time"
                    ]
                    overall_item_count_completed_cycle += category_data["count"]

                if overall_item_count_completed_cycle > 0:
                    self.last_cycle_overall_avg_response_time = (
                        overall_total_duration_completed_cycle
                        / overall_item_count_completed_cycle
                    )
                    self.last_cycle_overall_response_count = (
                        overall_item_count_completed_cycle
                    )
                    logging.info(
                        f"Fim do ciclo. Geral Ciclo (Proc+Log): {self.last_cycle_overall_avg_response_time:.3f}s ({self.last_cycle_overall_response_count} itens)"
                    )
                else:
                    self.last_cycle_overall_avg_response_time = None
                    self.last_cycle_overall_response_count = 0
                    logging.info(
                        "Fim do ciclo. Nenhum item com tempo no ciclo anterior (geral)."
                    )

                self.last_cycle_category_timing_snapshot = copy.deepcopy(
                    self.current_cycle_category_timing
                )
                for category_key in self.current_cycle_category_timing:
                    self.current_cycle_category_timing[category_key]["count"] = 0
                    self.current_cycle_category_timing[category_key]["total_time"] = 0.0

                logging.info(
                    f"--- Iniciando ciclo Priority Scheduling {len(self.sites)} sites às {time.strftime('%H:%M:%S')} ---"
                )
                print(
                    f"TERMINAL: --- Novo ciclo Priority Scheduling {len(self.sites)} sites às {time.strftime('%H:%M:%S')} ---"
                )
                priority_dispatch_queue = queue.PriorityQueue()
                dispatch_order_counter = 0
                for site_url in self.sites:
                    with self.lock:
                        last_known_status = self.status_dict.get(site_url, {}).get(
                            "status", "Aguardando 1ª checagem..."
                        )
                    priority_level = 2
                    if isinstance(last_known_status, int):
                        if last_known_status in [-1, -2, -3] or (
                            500 <= last_known_status < 600
                        ):
                            priority_level = 0
                        elif 400 <= last_known_status < 500:
                            priority_level = 1
                    elif last_known_status == "Aguardando 1ª checagem...":
                        priority_level = 1
                    priority_dispatch_queue.put(
                        (priority_level, dispatch_order_counter, site_url)
                    )
                    dispatch_order_counter += 1
                with self.lock:
                    self.results = queue.Queue()
                active_threads_this_cycle.clear()
                while not priority_dispatch_queue.empty():
                    try:
                        prio, _, site_to_check = priority_dispatch_queue.get_nowait()
                        logging.info(
                            f"Priority Scheduler: Despachando {site_to_check} (Prio: {prio})"
                        )
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
                    except queue.Empty:
                        break
                next_full_recheck_time = current_time + site_recheck_period
                logging.info(
                    f"Checagens despachadas. Próximo ciclo ~{time.strftime('%H:%M:%S', time.localtime(next_full_recheck_time))}."
                )

            with self.lock:
                while not self.results.empty():
                    try:
                        site, status_val, message_str, proc_log_duration_val = (
                            self.results.get_nowait()
                        )

                        self.status_dict[site] = {
                            "status": status_val,
                            "message": message_str,
                        }
                        made_updates_to_status_dict = True

                        if proc_log_duration_val is not None:
                            category_for_timing = None
                            if isinstance(status_val, int):
                                if 200 <= status_val < 300:
                                    category_for_timing = "Success"
                                elif 400 <= status_val < 500:
                                    category_for_timing = "Warning"
                                elif 500 <= status_val < 600:
                                    category_for_timing = "Error"

                            if category_for_timing:
                                self.timing_data[category_for_timing]["count"] += 1
                                self.timing_data[category_for_timing][
                                    "total_time"
                                ] += proc_log_duration_val

                                self.current_cycle_category_timing[category_for_timing][
                                    "count"
                                ] += 1
                                self.current_cycle_category_timing[category_for_timing][
                                    "total_time"
                                ] += proc_log_duration_val
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
        print("-" * 70)
        print("      Site Manager (Priority Scheduling - Thread per Check)")
        print("-" * 70)

        if not self.status_dict:
            print("Nenhum site para exibir.")
        else:
            display_items_with_priority = []
            temp_counter = 0
            for site_url_disp, data_disp in self.status_dict.items():
                last_known_status_disp = data_disp.get(
                    "status", "Aguardando 1ª checagem..."
                )
                priority_level_disp = 2
                if isinstance(last_known_status_disp, int):
                    if last_known_status_disp in [-1, -2, -3] or (
                        500 <= last_known_status_disp < 600
                    ):
                        priority_level_disp = 0
                    elif 400 <= last_known_status_disp < 500:
                        priority_level_disp = 1
                elif last_known_status_disp == "Aguardando 1ª checagem...":
                    priority_level_disp = 1
                display_items_with_priority.append(
                    {
                        "prio": priority_level_disp,
                        "counter": temp_counter,
                        "site": site_url_disp,
                        "data": data_disp,
                    }
                )
                temp_counter += 1
            sorted_display_items = sorted(
                display_items_with_priority, key=lambda x: (x["prio"], x["site"])
            )
            for item in sorted_display_items:
                site, data, prio_disp = item["site"], item["data"], item["prio"]
                status_val, message = data["status"], data["message"]
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
                display_site = site[:35] + "..." if len(site) > 38 else site
                print(
                    f"(P{prio_disp}) {display_site:<38}: {status_str:<18} ({message})"
                )

        print("-" * 70)
        print("Tempo Médio de Processamento e Log do Status (Geral Acumulado):")
        for category, data in self.timing_data.items():
            if data["count"] > 0:
                avg_time = data["total_time"] / data["count"]
                print(f"  - {category:<10}: {avg_time:.3f}s ({data['count']} amostras)")
            else:
                print(f"  - {category:<10}: N/A (0 amostras)")

        print("-" * 70)
        print(
            "Tempo Médio de Processamento e Log do Status (Ciclo Anterior por Status):"
        )
        if self.last_cycle_category_timing_snapshot:
            data_found_in_cycle_snapshot = False
            for category, data in self.last_cycle_category_timing_snapshot.items():
                if data["count"] > 0:
                    avg_time = data["total_time"] / data["count"]
                    print(
                        f"  - {category:<10}: {avg_time:.3f}s ({data['count']} itens no ciclo)"
                    )
                    data_found_in_cycle_snapshot = True
                else:
                    print(f"  - {category:<10}: N/A (0 itens no ciclo)")

            if self.last_cycle_overall_avg_response_time is not None:
                print(
                    f"  - Total Ciclo: {self.last_cycle_overall_avg_response_time:.3f}s ({self.last_cycle_overall_response_count} itens no ciclo)"
                )
            elif not data_found_in_cycle_snapshot:
                print(f"  - Total Ciclo: N/A (sem itens com tempo no ciclo anterior)")
        else:
            print(
                "  (Aguardando conclusão do primeiro ciclo para estatísticas por status)"
            )

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
    logging.info("============= Script SiteManager (Priority) Iniciado =============")
    print(
        "TERMINAL: ============= Script SiteManager (Priority) Iniciado ============="
    )
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
        manager.run_checks(screen_update_interval=1, site_recheck_period=10)
    except KeyboardInterrupt:
        print("\nTERMINAL: Saindo...")
        logging.info("Execução interrompida (Ctrl+C).")
    except Exception as e:
        logging.exception("Exceção não tratada no loop principal:")
        print(f"\nTERMINAL: Erro crítico: {e}")
    finally:
        logging.info(
            "============= Script SiteManager (Priority) Finalizado ============="
        )
        print(
            "TERMINAL: ============= Script SiteManager (Priority) Finalizado ============="
        )
