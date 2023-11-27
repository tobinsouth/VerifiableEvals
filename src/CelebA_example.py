# The problem is the CNNs are very parameter effient, so the circuits are HUGE

# In this example we're going to use MobileNetV2 and test on the celeba dataset

import os, json
import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, models, transforms
from torch.utils.data import DataLoader, random_split
from tqdm import tqdm
import ezkl

# Download dataset
os.makedirs('CelebA/data/ezkl_inputs', exist_ok=True)
os.makedirs('CelebA/data/ezkl_witnesses', exist_ok=True)
os.makedirs('CelebA/data/ezkl_proofs', exist_ok=True)

transform = transforms.Compose([
    transforms.Resize((112, 112)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])

dataset = datasets.CelebA('CelebA/data', download=False, transform=transform)

# Make a random train test split
train_dataset, test_dataset = torch.utils.data.random_split(dataset, [len(dataset)-1000, 1000])

device = torch.device("cuda" if torch.cuda.is_available() else "mps" if  torch.backends.mps.is_available() else "cpu")

train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
test_loader = DataLoader(test_dataset, batch_size=1)


from models.VariableCNN import SparseCNN

# Model initialization
model = SparseCNN()
if torch.cuda.device_count() > 1:
    print("Using", torch.cuda.device_count(), "GPUs!")
    model = nn.DataParallel(model)
model = model.to(device)


model = models.mobilenet_v3_small(pretrained=True)
model.classifier[3] = nn.Linear(1024, 40)
model = model.to(device)


# Loss function and optimizer
criterion = nn.BCEWithLogitsLoss()
optimizer = optim.Adam(model.parameters(), lr=0.1)

# Training loop
num_epochs = 3
for epoch in range(num_epochs):
    model.train()
    total_loss = 0
    for i, (images, labels) in enumerate(tqdm(train_loader)):
        images, labels = images.to(device), labels.to(device)
        
        optimizer.zero_grad()
        outputs = model(images)
        labels = labels.float()
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()

        total_loss += loss.item()

        if i % 100 == 0:
             print(f"Epoch [{epoch+1}], Loss: {total_loss/100:.4f}")
             total_loss=0
       

## 3. Export the model and data for ezkl to use
model.to("cpu")
example_input = next(iter(test_loader))[0][0].to("cpu")  # Ensure input is 4D: [1, C, H, W]
from utils.export import export
export(model, input_array=example_input, onnx_filename="CelebA/network.onnx", input_filename="CelebA/input.json")

LOGGING = True
os.makedirs('MNIST/logs', exist_ok=True)
pipstd = lambda fname: f" 2>&1 | tee MNIST/logs/{fname}.log" if LOGGING else ""
SRS_PATH = '../../kzgs/kzg%d.srs'


from thop import profile
macs, params = profile(model, inputs=(example_input.unsqueeze(0), ))
print(f"Total model params: {params}\nTotal model MACs (FLOPs): {macs}")

## 3.1 Setup and calibrate the model for proving using ezkl
# os.system("ezkl table -M CelebA/network.onnx" + pipstd('setup'))
os.system("ezkl gen-settings -M CelebA/network.onnx --settings-path=CelebA/settings.json --input-visibility='public'" + pipstd('setup'))
# ezkl.get_srs(SRS_PATH, "CelebA/settings.json")
os.system("ezkl calibrate-settings -M CelebA/network.onnx -D CelebA/input.json --settings-path=CelebA/settings.json" + pipstd('setup'))
settings = json.load(open('CelebA/settings.json', 'r'))
logrows = settings['run_args']['logrows']
ezkl.get_srs(SRS_PATH % logrows, "CelebA/settings.json")

os.system("ezkl compile-circuit -M CelebA/network.onnx -S CelebA/settings.json --compiled-circuit CelebA/network.ezkl" + pipstd('setup'))
os.system("ezkl gen-witness -M CelebA/network.ezkl -D CelebA/input.json --output CelebA/witnessRandom.json" + pipstd('setup'))
os.system("ezkl mock -M CelebA/network.ezkl --witness CelebA/witnessRandom.json" + pipstd('setup'))
os.system(f"ezkl setup -M CelebA/network.ezkl --srs-path={SRS_PATH % logrows} --vk-path=CelebA/vk.key --pk-path=CelebA/pk.key" + pipstd('setup'))