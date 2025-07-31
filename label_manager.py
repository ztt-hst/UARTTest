import json

class LabelManager:
    def __init__(self, label_file='label.json', default_language='EN'):
        self.label_file = label_file
        self.labels = {}
        self.current_language = default_language
        self.load_labels()

    def load_labels(self):
        try:
            with open(self.label_file, 'r', encoding='utf-8') as f:
                self.labels = json.load(f)
        except Exception as e:
            print(f"Error loading labels: {e}")
            self.labels = {}

    def get_label(self, key):
        if key in self.labels:
            return self.labels[key].get(self.current_language, key)
        return key

    def set_language(self, lang):
        self.current_language = lang 