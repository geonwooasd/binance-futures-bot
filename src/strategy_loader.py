import importlib

def load_strategy(path: str):
    mod = importlib.import_module(path)
    if not hasattr(mod, "generate_signal"):
        raise RuntimeError(f"{path} 에 generate_signal 함수가 없어요")
    return mod.generate_signal
