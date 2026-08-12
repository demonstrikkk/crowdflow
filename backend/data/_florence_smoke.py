import time

import torch
from PIL import Image, ImageDraw
from transformers import AutoModelForCausalLM, AutoProcessor

MODEL = "C:/Users/asus/Downloads/crowdflow/backend/models/florence-2-large"

img = Image.new("RGB", (800, 500), "white")
d = ImageDraw.Draw(img)
d.rectangle([40, 40, 760, 460], outline=(30, 30, 30), width=6)
d.line([(400, 46), (400, 180)], fill=(30, 30, 30), width=6)
d.text((120, 90), "GATE A", fill=(20, 20, 20))
d.text((430, 60), "ENTRANCE 2", fill=(20, 20, 20))

print("loading processor+model ...")
t0 = time.time()
processor = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL, trust_remote_code=True, attn_implementation="eager"
).eval()
print("load", round(time.time() - t0, 1), "s")

for task, args in (("<OCR_WITH_REGION>", None), ("<CAPTION_TO_PHRASE_GROUNDING>", "GATE A. ENTRANCE 2")):
    t0 = time.time()
    prompt = task
    if args:
        prompt = f"{task} {args}".rstrip()
    inputs = processor(text=prompt, images=img, return_tensors="pt")
    with torch.no_grad():
        ids = model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=512,
            num_beams=1,
        )
    text = processor.batch_decode(ids, skip_special_tokens=False)[0]
    out = processor.post_process_generation(text, task=task, image_size=img.size)
    print("===", task, round(time.time() - t0, 1), "s")
    print(out)
