This ComfyUI custom node lets you save and load latent image and conditioning triplets. 

I made this so I can batch a bunch of Wan 2.2 high noise inference latents and then finish them off with the low noise
model so that generating videos don't all waste time waiting for that VRAM shuffle.

In order to use this: 

1. take your working wan video gen workflow and make two copies
2. in the first one (high noise stage A) put the output latent of the first ksampler and its conditioning into the save node.
3. in the second one (low noise stage B) use the load node and pipe all outputs into the second ksampler.
4. you can delete the unused nodes, so stage A only has a high noise model load in it, and stage B only has a low noise
   model load in it!
5. When generating with this technique if you make a batch of size N outputs, just queue up N jobs of stage A and then N
   jobs of stage B after. Just make sure to consume the queue of saved latents.
6. Profit by only wasting the time to load the model to the GPU **one time**.

## Install

Clone/copy this folder into `ComfyUI/custom_nodes/save-load-lat-cond/` and restart ComfyUI.

## Nodes

### Save Latent + Cond (Queue)

Inputs:
- `latent`, `positive`, `negative`
- `mode`: `cpu` (fast, process-local, frees VRAM), `gpu` (fastest, keeps tensors on GPU), or `disk` (persistent)
- `queue_name`: optional queue key (default `default`)

This node is an output node (no outputs); put it at the end of your Stage A workflow.

### Load Latent + Cond (Queue)

Inputs:
- `mode`: `cpu`, `gpu`, or `disk` (must match where you saved to)
- `queue_name`: must match what you saved to
- `consume`: if true, deletes the item after reading it (default true)
- `reset_cursor`: if true, starts reading from the beginning again (default false)

Note: when `consume=false`, the loader still advances an internal per-queue cursor so repeated runs move forward instead of reusing the same first item.

## Disk location

When `storage=disk`, items are saved as `.pt` files under ComfyUI's output directory:
`<output>/save_load_lat_cond/<queue_name>/`
