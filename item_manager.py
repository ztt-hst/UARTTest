import json

class ItemManager:
    def __init__(self, json_file='uart_command_set.json', language='EN'):
        self.json_file = json_file
        self.language = language
        self.items = []
        self.organized_items = {}
        self.load_items()

    def load_items(self):
        try:
            with open(self.json_file, 'r', encoding='utf-8') as f:
                self.items = json.load(f)
        except Exception as e:
            print(f"Error loading JSON file: {e}")
            self.items = []
        self.organize_items()

    def organize_items(self):
        self.organized_items = {}
        for item in self.items:
            module = item.get("Module" if self.language == "EN" else "模块", "Uncategorized")
            submodule = item.get("Submodule" if self.language == "EN" else "子模块", "Others")
            if module not in self.organized_items:
                self.organized_items[module] = {}
            if submodule not in self.organized_items[module]:
                self.organized_items[module][submodule] = []
            self.organized_items[module][submodule].append(item)

    def set_language(self, lang):
        self.language = lang
        self.organize_items()

    def get_organized_items(self):
        return self.organized_items 