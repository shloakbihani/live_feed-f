# Daycare fine-tune metrics

Date: 15 Oct 2026

The previous classifier called violence on daycare scenes that are safe. On the labeled safe frames it was wrong 32% of the time, and those mistakes were scored at about 96% confidence, so raising `VIOLENCE_CONF` does not fix them.

The installed model is the classification-head fine-tune in `runs/violence_daycare_ft`. A second, lower learning-rate run was worse and was not installed.

## Installed weights

| File | Role |
|---|---|
| `pi/violence_yolov8n_cls-4/weights/best.pt` | Original model, left in place |
| `pi/violence_yolov8n_cls-4/weights/best_daycare_ft.pt` | Fine-tuned model the monitor loads |
| `ml-model/violence_yolov8n_cls-4/weights/best_daycare_ft.pt` | Same fine-tuned checkpoint |
| `runs/violence_daycare_ft/weights/best.pt` | Selected checkpoint (epoch 2) |

The monitor reads `VIOLENCE_WEIGHTS`. Restart it after copying `best_daycare_ft.pt` onto the Pi.

## Setup

| Item | Value |
|---|---|
| Base model | YOLOv8n-cls, original `best.pt` |
| Task | 2-class classifier: `non_violence`, `violence` |
| Image size | 224 |
| Device | CPU (Apple M4) |
| Trainable part | Classification head only (`freeze=9`) |
| Optimizer | AdamW |
| Learning rate | 0.001 |
| Batch | 32 |
| Epochs requested | 20 |
| Early stop | patience 5; stopped after epoch 7 |
| Best epoch | 2 (highest validation top-1, 0.96) |
| Wall time | 39.4 s through epoch 7; about 0.011 h |

Dataset built by `prepare_finetune.py` from `ml-model/data`. One alert timestamp is one event. Duplicate `Copy of …` files were dropped.

| Split | non_violence | violence |
|---|---|---|
| Train | 297 | 78 (3 events, repeated, plus frames from their clips) |
| Val | 74 | 1 |

Held-out violence event, never used in training: `alert_20260924_173127`.

## Epoch log (selected run)

Source: `runs/violence_daycare_ft/results.csv`

| Epoch | Train loss | Val loss | Val top-1 | Val top-5 | Time (s) |
|---|---|---|---|---|---|
| 1 | 1.873 | 0.111 | 0.907 | 1.0 | 6.0 |
| **2** | **1.051** | **0.087** | **0.960** | **1.0** | **11.9** |
| 3 | 0.649 | 0.202 | 0.907 | 1.0 | 17.5 |
| 4 | 0.476 | 0.445 | 0.853 | 1.0 | 22.9 |
| 5 | 0.406 | 0.179 | 0.867 | 1.0 | 28.4 |
| 6 | 0.275 | 0.172 | 0.933 | 1.0 | 33.9 |
| 7 | 0.208 | 0.087 | 0.960 | 1.0 | 39.4 |

Top-5 is 1.0 on every epoch because there are only two classes. Epoch 7 matched epoch 2's top-1, and early stopping kept epoch 2.

Validation top-1 is mostly safe frames (74 of 75). Use the table below for the violence class.

## Before vs after

Scored at 224×224 on the original stills. "Safe, called violence" uses the 74 validation frames the fine-tune did not train on.

| Check | Original model | Fine-tuned (epoch 2) |
|---|---|---|
| Safe val frames called violence | 24/74 (32.4%) | 2/74 (2.7%) |
| Safe train frames called violence | 81/297 (27.3%) | 14/297 (4.7%) |
| `alert_20260721_174427` (train) | violence 0.78 | violence 0.99 |
| `alert_20260811_160522` (train) | violence 0.98 | violence 0.97 |
| `alert_20260811_160548` (train) | violence 0.76 | violence 0.93 |
| `alert_20260924_173127` (held out) | violence 0.85 | non_violence 0.10 |

False alarms on unseen safe frames fell from 32.4% to 2.7%. The three violence events that were in training are still detected. The one held-out incident is missed (0.85 → 0.10). Four real violence events is not enough for the model to recognize a new incident that does not look like the three it was shown.

## Rejected run

`runs/violence_daycare_ft_gentle` used the same data with learning rate 0.0003 for 6 epochs. Its best validation top-1 was 0.88, and it dropped three of the four violence clips below 0.5 while only cutting safe-frame false alarms to about 11–18%. Those weights were not installed.

| Epoch | Train loss | Val top-1 |
|---|---|---|
| 1 | 1.928 | 0.840 |
| 2 | 1.144 | 0.880 |
| 3 | 0.907 | 0.827 |
| 4 | 0.980 | 0.840 |
| 5 | 0.775 | 0.827 |
| 6 | 0.838 | 0.813 |

## Train again

Put new confirmed clips in `ml-model/data/violence` and `ml-model/data/non_violence`, then:

```bash
cd ml-model
python3 prepare_finetune.py
python3 train_finetune.py
```

Check the new held-out violence clip, then copy the checkpoint to `pi/violence_yolov8n_cls-4/weights/best_daycare_ft.pt`. Leave `best.pt` as the original model.

## Action fine-tune (27 Oct 2026)

Three new clips in `ml-model/new_data` (`violence.mp4`, `violence2.mp4`, `violence3.mp4`) were added. The head was trained from `best_daycare_ft.pt` with `prepare_action_ft.py` and `train_action_ft.py`. `best.pt` and `best_daycare_ft.pt` were left in place. The monitor now loads `best_action_ft.pt`.

| Item | Value |
|---|---|
| Frames | 2 per second, long side 640 |
| Train | 299 calm, 250 violence |
| Val | 74 calm, 32 violence |
| Device | Apple M4 (MPS) |
| Learning rate | 0.0004, head only (`freeze=9`), 12 epochs |
| Best val top-1 | 0.991 |

On every sampled frame of the three clips, frames at or above 60% violence:

| Clip | Before (`best_daycare_ft`) | After (`best_action_ft`) |
|---|---|---|
| violence.mp4 | 9/28 | 28/28 |
| violence2.mp4 | 32/95 | 95/95 |
| violence3.mp4 | 8/32 | 32/32 |

Calm validation frames called unsafe: 2/74 before, 1/74 after.
