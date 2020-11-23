import warnings
from typing import Dict, List

import torch
import torch.nn as nn
from torchvision.models.resnet import resnet18, resnet50


class DriveNetModel(nn.Module):
    def __init__(
        self,
        model_arch: str,
        num_input_channels: int,
        step_time_s: float,
        num_targets: int,
        weights_scaling: List[float],
        criterion: nn.Module,
        pretrained: bool = True,
    ) -> None:
        super().__init__()
        self.model_arch = model_arch
        self.num_input_channels = num_input_channels
        self.step_time_s = step_time_s
        self.num_targets = num_targets
        self.register_buffer("weight_scaling", torch.tensor(weights_scaling))
        self.pretrained = pretrained
        self.criterion = criterion

        if pretrained and self.num_input_channels != 3:
            warnings.warn("There is no pre-trained model with num_in_channels != 3, first layer will be reset")

        if model_arch == "resnet18":
            self.model = resnet18(pretrained=pretrained)
            self.model.fc = nn.Linear(in_features=512, out_features=num_targets)
        elif model_arch == "resnet50":
            self.model = resnet50(pretrained=pretrained)
            self.model.fc = nn.Linear(in_features=2048, out_features=num_targets)
        else:
            raise NotImplementedError(f"Model arch {model_arch} unknown")

        if self.num_input_channels != 3:
            self.model.conv1 = nn.Conv2d(
                self.num_input_channels, 64, kernel_size=(7, 7), stride=(2, 2), padding=(3, 3), bias=False
            )

    def forward(self, data_batch: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        image_batch = data_batch["image"]
        outputs = self.model(image_batch)
        batch_size = len(data_batch["image"])

        if self.training:
            if self.criterion is None:
                raise NotImplementedError("Loss function is undefined.")

            targets = (torch.cat((data_batch["target_positions"], data_batch["target_yaws"]), dim=2)).view(
                batch_size, -1
            )
            target_weights = (data_batch["target_availabilities"].unsqueeze(-1) * self.weights_scaling).view(
                batch_size, -1
            )
            loss = torch.mean(self.criterion(outputs, targets) * target_weights)
            train_dict = {"loss": loss}
            return train_dict
        else:
            predicted = outputs.view(batch_size, -1, 3)
            pred_positions = predicted[:, :, :2]
            pred_yaws = predicted[:, :, 2:3]
            # compute velocities
            cur_positions = torch.zeros(batch_size, 1, 2, device=pred_positions.device)
            # [batch_size, num_timestamps, 2]
            pred_velocities = (
                pred_positions - torch.cat((cur_positions, pred_positions[:, :-1, :]), dim=1)
            ) / self.step_time_s
            eval_dict = {"positions": pred_positions, "yaws": pred_yaws, "velocities": pred_velocities}
            return eval_dict
