import requests
import time
import dateutil.parser
from dto.config import Config
from dto.metrics import Metrics


class HTTPClient:
    def __init__(self, config: Config):
        self.config = config
        self.metrics: Metrics = Metrics()
        self.headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def get_metrics(self):
        self.metrics = Metrics()
        t1 = time.time()
        servers = self.fetch_server()
        pages = servers['meta']['pagination']['total_pages']

        for page in range(1, pages + 1):
            servers = self.fetch_server(page)
            for server_data in servers.get('data', []):
                if not (bool(server_data['attributes']['is_suspended']) or
                        bool(server_data['attributes']['is_installing'])):
                    self.process_servers(server_data)

        for page in range(1, pages + 1):
            for index, server_id in enumerate(self.metrics.id):
                resources = self.fetch_resources(server_id, index, page)
                self.process_resources(resources)
                self.fetch_last_backup_time(server_id, index, page)
                minecraft_info = self.fetch_minecraft_info(server_id, index)
                self.process_minecraft_info(minecraft_info, index)
                
        t2 = time.time()
        print(f"total= {t2 - t1}")
        return self.metrics

    def fetch_server(self, page=1):
        url = f"{self.get_url()}/api/client/?type={self.config.server_list_type}&page={page}"
        response = requests.get(url, headers=self.headers, verify=not self.config.ignore_ssl)
        if response.status_code != 200:
            raise Exception(f"Error fetching servers: {response.text}")
        response.close()
        return response.json()

    def process_servers(self, server_data):
        attributes = server_data.get('attributes', {})
        self.metrics.name.append(attributes.get('name', ''))
        self.metrics.id.append(attributes.get('identifier', ''))
        self.metrics.max_memory.append(attributes['limits']['memory'])
        self.metrics.max_swap.append(attributes['limits']['swap'])
        self.metrics.max_disk.append(attributes['limits']['disk'])
        self.metrics.io.append(attributes['limits']['io'])
        self.metrics.max_cpu.append(attributes['limits']['cpu'])

    def fetch_resources(self, server_id, index, page):
        url = f"{self.get_url()}/api/client/servers/{server_id}/resources?page={page}"
        response = requests.get(url, headers=self.headers, verify=not self.config.ignore_ssl)
        if response.status_code != 200:
            raise Exception(f"Fetch metrics for {self.metrics.name[index]}")
        response_data = response.json()
        response.close()
        return response_data["attributes"]["resources"]

    def process_resources(self, resources):
        self.metrics.memory.append(self.convert_byte_to_mebibyte(resources["memory_bytes"]))
        self.metrics.cpu.append(resources["cpu_absolute"])
        self.metrics.disk.append(self.convert_byte_to_mebibyte(resources["disk_bytes"]))
        self.metrics.rx.append(self.convert_byte_to_mebibyte(resources["network_rx_bytes"]))
        self.metrics.tx.append(self.convert_byte_to_mebibyte(resources["network_tx_bytes"]))
        self.metrics.uptime.append(resources["uptime"])

    def fetch_last_backup_time(self, server_id, index, page):
        url = f"{self.get_url()}/api/client/servers/{server_id}/backups?per_page=50&page={page}"
        response = requests.get(url, headers=self.headers, verify=not self.config.ignore_ssl)
        if response.status_code != 200:
            raise Exception(f"Fetch last backup for {self.metrics.name[index]}")
        response_data = response.json()
        response.close()
        backups = response_data["data"]
        last_successful_backup = max(
            (dateutil.parser.isoparse(backup["attributes"]["completed_at"]).timestamp()
             for backup in backups
             if backup["attributes"]["is_successful"]), default=0
        ) if backups else 0
        self.metrics.last_backup_time.append(last_successful_backup)
        
    # Add these methods to the HTTPClient class
    def fetch_minecraft_info(self, server_id, index):
        #print(server_id)
        url = f"{self.get_url()}/api/client/servers/{server_id}/minecraft-info"
        try:
            response = requests.get(url, headers=self.headers, verify=not self.config.ignore_ssl)
            if response.status_code != 200:
                print(f"Error fetching Minecraft info for {self.metrics.name[index]}: {response.text}")
                return {'success':False}
            return response.json()
        except Exception as e:
            print(f"Error fetching Minecraft info for {self.metrics.name[index]}: {e}")
            return {'success':False}
        
    def process_minecraft_info(self, minecraft_info, index):
        # Default values
        version_name = "unknown"
        version_protocol = 0
        players_online = 0
        players_max = 0
    
        if isinstance(minecraft_info, dict) and minecraft_info["success"] == True:
            data = minecraft_info.get("data", {})
            version = data.get("version", {})
            players = data.get("players", {})
        
            version_name = version.get("name", "unknown")
            players_online = players.get("online", 0)
            players_max = players.get("max", 0)
            try:
                version_protocol = int(version.get("protocol", 0))
            except (TypeError, ValueError):
                version_protocol = 0
    
        # Append to metrics
        self.metrics.players_online.append(players_online)
        self.metrics.players_max.append(players_max)
        self.metrics.version_name.append(version_name)
        self.metrics.version_protocol.append(version_protocol)
        
    def get_url(self):
        if self.config.https:
            return f"https://{self.config.host}:{self.config.host_port if self.config.host_port else 443}"
        return f"http://{self.config.host}:{self.config.host_port if self.config.host_port else 80}"

    @staticmethod
    def convert_byte_to_mebibyte(byte):
        return byte / 1048576
