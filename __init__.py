from .nodes import LoadLatentCond, PickPathByIndex, PickSubdirectory, SaveLatentCond

WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {
    "SaveLatentCond": SaveLatentCond,
    "LoadLatentCond": LoadLatentCond,
    "PickSubdirectory": PickSubdirectory,
    "PickPathByIndex": PickPathByIndex,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SaveLatentCond": "Save Latent + Cond (Queue)",
    "LoadLatentCond": "Load Latent + Cond (Queue)",
    "PickSubdirectory": "Pick Subdirectory (Index)",
    "PickPathByIndex": "Pick Path By Index",
}
