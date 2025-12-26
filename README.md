This is a collection of ComfyUI custom nodes I made to streamline some more "batchy" workflows. 

There are 2 groups of functionality so far: 

1. Save/Load Latent + Conditioning nodes: Save and load latent image and conditioning triplets.

   I made this so I can batch a bunch of Wan 2.2 high noise inference latents and then finish them off with the low noise
   model so that generating videos don't waste a bunch of time waiting for that VRAM to evict the high noise model and
   load in the low noise model for EACH generation. The tradeoff is that you have to split this processing into two
   workflows and batch them separately, so you don't get to see intermediate results while you run a big batch.

   In order to use this: 

   1. take your working wan video gen workflow and make two copies of it.
   2. in the first one (high noise inference, call it stage A) put the output latent of the first ksampler and its conditioning inputs into the Save node.
   3. in the second one (low noise inference, call it stage B) use the Load node, and pipe all outputs into the second ksampler.
   4. you can delete the unused nodes, so stage A workflow only has your high noise model load in it, and stage B workflow only has a low noise
      model load in it!
   5. When generating with this technique if you make a batch of size N outputs, just queue up N jobs of stage A and then N
      jobs of stage B after.

2. Pick Path by Index node: Batch iterate through inputs, usable for images, video files, and video frame dirs.

   This one allows for a streamlined way to capture the behavior of specifying a directory in which inputs are staged
   for pipelined ingestion in batches. Furthermore, this provides useful string output of the basename of the path
   chosen, so you can wire that up into the outputs, making it much easier to correlate the names of the inputs used by
   the workflow with the names of its output products. 

   You can prepare N images or videos in a dir, or even subdirs each containing the frames of a video (much better
   quality, highly recommended), set the after generation behavior to increment on the integer index and watch comfyui
   chug along running the workflow against everything. 

## Install

Clone/copy this folder into `ComfyUI/custom_nodes/save-load-lat-cond/` and restart ComfyUI.

## Nodes

### Save Latent + Cond (Queue)

Inputs:
- `latent`, `positive`, `negative`
- `mode`: `cpu` (fast, process-local, frees VRAM), `gpu` (fastest, keeps tensors on GPU), or `disk` (persistent)
- `queue_name`: optional queue key (default `default`)

This node is an output node (no outputs); put it at the end of your Stage A workflow.

After it runs, the node UI shows a `Queue` widget with the unread items (timestamps) and queue size for the selected `mode` + `queue_name`.

### Load Latent + Cond (Queue)

Inputs:
- `mode`: `cpu`, `gpu`, or `disk` (must match where you saved to)
- `queue_name`: must match what you saved to
- `consume`: if true, deletes the item after reading it (default true)
- `reset_cursor`: if true, starts reading from the beginning again (default false)

Note: when `consume=false`, the loader still advances an internal per-queue cursor so repeated runs move forward instead of reusing the same first item.

After it runs, the node UI shows a `Queue` widget with the remaining unread items (timestamps) plus the queue size before/after the load.

The load node also exposes a `cursor` widget/output (0-based index of the next unread item in the current sorted list):
- `cursor=-1` uses the internal per-queue cursor (default behavior)
- `reset_cursor=true` starts from `cursor=0`
- setting `cursor>=0` overrides where the next load starts

### Pick Path By Index

Inputs:
- `root_dir`: a directory containing items to pick from
- `kind`: `dirs` or `files`
- `index`: 0-based entry index.
  - This node sets the `index` widget default `control_after_generate` to `increment` (so queue batching “just works”).
  - You can switch it back to fixed in the UI via the widget’s “Control after generate” option.
- `sort`: `natural` (default), `name`, `name_desc`, `mtime`, `mtime_desc`
- `on_out_of_range`: `wrap` (default), `error`, or `clamp`
- `include_regex` / `exclude_regex`: optional filters applied to entry names
- `extensions`: file-only filter (comma-separated, e.g. `.png,.jpg,.webp`; empty means allow all)

Outputs:
- `path`: full path to the selected entry
- `name`: basename
- `stem`: basename without extension
- `index`, `total`

Notes:
- `on_out_of_range=wrap` uses modulo (`index % total`) so the selection cycles.
- The node shows a live “Selection” preview in the node UI (and updates after execution too).

### Pick Subdirectory (Index) [Deprecated]

This is kept for old workflows, but `PickPathByIndex(kind=dirs)` replaces it.

Inputs:
- `root_dir`: a directory containing subdirectories (e.g. one subdir per video, each containing PNG frames)
- `index`: which subdirectory to pick (supports increment-after-generate)
- `sort`: `natural` (default), `name`, `name_desc`, `mtime`, `mtime_desc`
- `on_out_of_range`: `error` (default), `clamp`, or `wrap`
- `include_regex` / `exclude_regex`: optional filters applied to subdirectory names

Outputs:
- `dir_path`: full path to the selected subdirectory (wire this into nodes like Inspire's "Load image batch from dir")
- `dir_name`, `index`, `total`

## Disk location

When `storage=disk`, items are saved as `.pt` files under ComfyUI's output directory:
`<output>/save_load_lat_cond/<queue_name>/`
