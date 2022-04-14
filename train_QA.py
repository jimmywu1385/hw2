import pickle
import json
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Dict

import torch
from tqdm import trange
from transformers import BertTokenizer

from dataset import QAData
from model import QA

TRAIN = "train"
VALID = "valid"
SPLITS = [TRAIN, VALID]

def set_random(seed):
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True

def main(args):
    set_random(args.random_seed)

    tokenizer = BertTokenizer.from_pretrained(args.pretrained_path)

    data_paths = {split: args.cache_dir / f"{split}.json" for split in SPLITS}
    data = {split: json.loads(path.read_text()) for split, path in data_paths.items()}
    datasets: Dict[str, QAData] = {
        split: QAData(split_data, tokenizer)
        for split, split_data in data.items()
    }
    # TODO: crecate DataLoader for train / dev datasets
    train_datasets = torch.utils.data.DataLoader(datasets["train"], batch_size=args.batch_size, collate_fn=datasets["train"].collate_fn, shuffle=True)
    valid_datasets = torch.utils.data.DataLoader(datasets["valid"], batch_size=args.batch_size, collate_fn=datasets["valid"].collate_fn, shuffle=False)

    # TODO: init model and move model to target device(cpu / gpu)
    model = QA(args.pretrained_path, "train").to(args.device)

    # TODO: init optimizer
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    epoch_pbar = trange(args.num_epoch, desc="Epoch")
    
    for epoch in epoch_pbar:
        # TODO: Training loop - iterate over train dataloader and update model weights
        model.train()
        train_loss = 0.0
        train_correct = 0.0
        train_total = 0.0
        for i, dic in enumerate(train_datasets):
            input_ids = dic["input_ids"].to(args.device)
            token_type_ids = dic["token_type_ids"].to(args.device)
            attention_mask = dic["attention_mask"].to(args.device)
            start = dic["start"].to(args.device)
            end = dic["end"].to(args.device)

            output = model(input_ids, token_type_ids, attention_mask, start, end)
            loss = output.loss
            start_logits = output.start_logits
            end_logits = output.end_logits

            loss = loss/args.accum_size

            train_correct += ((start_logits.argmax(1) == start) & 
                              (end_logits.argmax(1) == end)).sum().item()
            train_total += len(start_logits)

            loss.backward()
            if (i+1) % args.accum_size == 0:
                optimizer.step()
                optimizer.zero_grad()

            train_loss += loss.item()
            if i % 10 == 0:
                print(f"epoch : {epoch + 1}, iter : {i + 1:5d} loss: {train_loss / (i+1):.5f}")
                print(f"EM : {train_correct / train_total} ")
        
        print(f"EM : {train_correct / train_total} ")

        # TODO: Evaluation loop - calculate accuracy and save model weights
        print("------eval start------\n")

        model.eval()
        valid_loss = 0.0
        valid_correct =0.0
        valid_total =0.0
        for i, dic in enumerate(valid_datasets):
            input_ids = dic["input_ids"].to(args.device)
            token_type_ids = dic["token_type_ids"].to(args.device)
            attention_mask = dic["attention_mask"].to(args.device)
            start = dic["start"].to(args.device)
            end = dic["end"].to(args.device)

            with torch.no_grad():
                output = model(input_ids, token_type_ids, attention_mask, start, end)
                loss = output.loss
                start_logits = output.start_logits
                end_logits = output.end_logits
            
                valid_correct += ((start_logits.argmax(1) == start) & 
                              (end_logits.argmax(1) == end)).sum().item()
                valid_total += len(start_logits)

            valid_loss += loss.item()
            if i % 10 == 0:
                print(f"epoch : {epoch + 1}, iter : {i + 1:5d} loss: {valid_loss / (i+1):.5f}")
                print(f"EM : {valid_correct / valid_total} ")

        print(f"EM : {valid_correct / valid_total} ")
    
    print("DONE\n")

    with open(args.ckpt_dir / Path("config.pkl"), "wb") as f:
        pickle.dump(model.bert.config, f)
    torch.save(model.state_dict(), args.ckpt_dir / args.model_name)


def parse_args() -> Namespace:
    parser = ArgumentParser()
    parser.add_argument("--random_seed", type=int, default=123)

    parser.add_argument(
        "--cache_dir",
        type=Path,
        help="Directory to the preprocessed caches.",
        default="./cache/QA",
    )
    parser.add_argument(
        "--ckpt_dir",
        type=Path,
        help="Directory to save the model file.",
        default="./ckpt/QA",
    )
    parser.add_argument(
        "--tokenizer_dir",
        type=Path,
        help="Directory to save the tokenizer file.",
        default="./ckpt/tokenizer",
    )
    parser.add_argument(
        "--model_name",
        type=Path,
        help="model name.",
        default="model.pt",
    )

    # optimizer
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--weight_decay", type=float, default=1e-4)

    # data loader
    parser.add_argument("--batch_size", type=int, default=1)
    parser.add_argument("--accum_size", type=int, default=2)

    # training
    parser.add_argument(
        "--max_len", type=int, help="sequence len", default=510
    )    
    parser.add_argument(
        "--device", type=torch.device, help="cpu, cuda, cuda:0, cuda:1", default="cpu"
    )
    parser.add_argument("--num_epoch", type=int, default=1)

    # model
    parser.add_argument(
        "--pretrained_path",
        type=str,
        help="model path.",
        default="bert-base-chinese",
    )

    args = parser.parse_args()
    return args

if __name__ == "__main__":
    args = parse_args()
    args.ckpt_dir.mkdir(parents=True, exist_ok=True)
    args.tokenizer_dir.mkdir(parents=True, exist_ok=True)
    main(args)