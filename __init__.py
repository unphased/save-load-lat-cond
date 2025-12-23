from .nodes import LoadLatentCond, SaveLatentCond

WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {
    "SaveLatentCond": SaveLatentCond,
    "LoadLatentCond": LoadLatentCond,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SaveLatentCond": "Save Latent + Cond (Queue)",
    "LoadLatentCond": "Load Latent + Cond (Queue)",
}
