
import yaml
import os
import shutil
from pathlib import Path
from typing import Dict, Any, Optional

class SettingsManager:
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config_path = Path(config_path)
        self.config_data = {}
        self._load()

    def _load(self):
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                self.config_data = yaml.safe_load(f) or {}
        else:
            self.config_data = {}

    def get_settings(self) -> Dict[str, Any]:
        """
        Return settings. 
        Note: We might want to mask secrets here if we were being strict, 
        but for a local single-user tool, returning them allows the user to see what's set.
        """
        # Reload to ensure we have the latest
        self._load() 
        
        # We can also attempt to read from .env to show what's effective, 
        # but that might be confusing if they edit it and it doesn't change the file.
        # For now, let's just show what is in the yaml file.
        return self.config_data

    def save_settings(self, new_settings: Dict[str, Any]) -> bool:
        try:
            # We explicitly define the structure we want to save
            # to avoid saving random garbage or frontend metadata
            
            # Deep merge or selective update
            # For simplicity, we assume new_settings contains the relevant sections
            
            # Helper to update nested dicts
            def update(d, u):
                for k, v in u.items():
                    if isinstance(v, dict):
                        d[k] = update(d.get(k, {}), v)
                    else:
                        d[k] = v
                return d

            update(self.config_data, new_settings)
            
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_path, 'w') as f:
                yaml.dump(self.config_data, f, default_flow_style=False, sort_keys=False)
            
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def get_effective_config(self) -> Dict[str, Any]:
        """
        Returns the config as it would be seen by the Scraper 
        (injecting env vars). Useful for debugging.
        """
        config = self.get_settings().copy()
        
        def inject(key, env_var):
             if val := os.getenv(env_var):
                 # traverse and set
                 parts = key.split('.')
                 curr = config
                 for part in parts[:-1]:
                     curr = curr.setdefault(part, {})
                 curr[parts[-1]] = val
        
        inject("tmdb.api_key", "TMDB_API_KEY")
        inject("omdb.api_key", "OMDB_API_KEY")
        inject("google.api_key", "GOOGLE_API_KEY")
        inject("google.search_engine_id", "GOOGLE_SEARCH_ENGINE_ID")
        inject("model.api_key", "MODEL_API_KEY")
        inject("model.base_url", "MODEL_BASE_URL")
        
        return config
