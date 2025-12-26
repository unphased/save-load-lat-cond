from .nodes import LoadLatentCond, PickSubdirectory, SaveLatentCond

WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {
    "SaveLatentCond": SaveLatentCond,
    "LoadLatentCond": LoadLatentCond,
    "PickSubdirectory": PickSubdirectory,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SaveLatentCond": "Save Latent + Cond (Queue)",
    "LoadLatentCond": "Load Latent + Cond (Queue)",
    "PickSubdirectory": "Pick Subdirectory (Index)",
}
