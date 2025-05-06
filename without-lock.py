import requests
import queue
from concurrent.futures import ThreadPoolExecutor
import time
import os


class SiteManager:
    def __init__(self, sites):
        self.sites = sites
        self.results = queue.Queue()
        self.status_dict = {}
        self.last_update = 0

    def check_status(self, site):
        try:
            response = requests.get(site, timeout=5)
            status = response.status_code
            if 200 <= status < 300:
                if site == "https://www.uuidtools.com/api/generate/v2":
                    message = f"Online (UUID: {response.content.decode()}) - {response.elapsed.total_seconds()}s"
                elif site == "https://www.uuidtools.com/api/generate/v4":
                    message = f"Online (UUID: {response.content.decode()}) - {response.elapsed.total_seconds()}s"
                else:
                    message = f"Online - {response.elapsed.total_seconds()}s"
            elif status == 404:
                message = f"Page not found - {response.elapsed.total_seconds()}s"
            elif 400 <= status < 500:
                message = f"Client Error (4xx) - {response.elapsed.total_seconds()}s"
            elif 500 <= status < 600:
                message = f"Server Error (5xx) - {response.elapsed.total_seconds()}s"
            else:
                message = (
                    f"Unknown status ({status}) - {response.elapsed.total_seconds()}s"
                )

        except requests.exceptions.RequestException as e:
            message = f"Connection Error"
            status = -1

        self.results.put((site, status, message))

    def run_checks(self, num_threads=4, update_interval=1):
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            for site in self.sites:
                self.status_dict[site] = {"status": "Checking...", "message": ""}

            while True:
                self.results = queue.Queue()

                for site in self.sites:
                    executor.submit(self.check_status, site)

                time.sleep(0.5)

                while not self.results.empty():
                    try:
                        site, status, message = self.results.get()
                        self.status_dict[site] = {
                            "status": status,
                            "message": message,
                        }
                    except queue.Empty:
                        break

                if time.time() - self.last_update >= update_interval:
                    self.update_screen()
                    self.last_update = time.time()

    def update_screen(self):
        os.system("cls" if os.name == "nt" else "clear")
        print("-" * 40)
        print("          Site Manager (SEM LOCKS)")
        print("-" * 40)

        for site, data in self.status_dict.items():
            status = data["status"]
            message = data["message"]

            if isinstance(status, int) and 200 <= status < 300:
                status_str = f"\033[92m{status}\033[0m"
            elif status == -1:
                status_str = f"\033[91mError\033[0m"
            elif isinstance(status, int) and 400 <= status < 600:
                status_str = f"\033[93m{status}\033[0m"
            else:
                status_str = str(status)

            print(f"- {site:<30}: {status_str:<15} ({message})")

        print("-" * 40)
        print(f"Last update: {time.strftime('%H:%M:%S')}")
        print("Press Ctrl+C to exit.")


if __name__ == "__main__":
    sites_to_check = [
        "https://www.google.com",
        "https://httpbin.org/delay/2",
        "https://httpbin.org/status/404",
        "https://httpbin.org/status/500",
        "https://siteee.com",
        "https://www.example.com",
        "https://www.uuidtools.com/api/generate/v2",
        "https://www.uuidtools.com/api/generate/v4",
        "https://httpbin.org/delay/3",
        "https://httpbin.org/status/418",
    ]

    manager = SiteManager(sites_to_check)

    try:
        num_sites = len(sites_to_check)
        manager.run_checks(num_threads=num_sites, update_interval=1)
    except KeyboardInterrupt:
        print("\nExiting...")
