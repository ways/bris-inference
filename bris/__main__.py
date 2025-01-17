import logging
from argparse import ArgumentParser
import numpy as np
import os

from hydra.utils import instantiate

import bris.routes
import bris.utils
from bris.data.datamodule import DataModule
from anemoi.utils.dates import frequency_to_seconds

from .checkpoint import Checkpoint
from .inference import Inference
from .predict_metadata import PredictMetadata
from .utils import create_config
from .writer import CustomWriter

LOGGER = logging.getLogger(__name__)

def main():
    parser = ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--config", type=str, required=True)

    config = create_config(parser)

    # Load checkpoint, and patch it if needed
    checkpoint = Checkpoint(config.checkpoint_path)

    # Chunking encoder and decoder, default 1
    checkpoint.set_encoder_decoder_num_chunks(
        getattr(config, "inference_num_chunks", 1)
    )
    if hasattr(config.model, "graph"):
        LOGGER.info("Update graph is enabled. Proceeding to change internal graph")
        checkpoint.update_graph(config.model.graph)  # Pass in a new graph if needed

    datamodule = DataModule(
        config=config,
        checkpoint_object=checkpoint,
    )
    
    # Assemble outputs
    run_name = config.run_name #"legendary_gnome"
    workdir = config.hardware.paths.workdir #"testdir"
    num_members = 1

    # Get outputs and required_variables of each decoder
    timestep = frequency_to_seconds(config.timestep)
    leadtimes = np.arange(config.leadtimes) * timestep
    decoder_outputs = bris.routes.get(
        config["routing"], leadtimes, num_members, datamodule, run_name, workdir
    )  # get num_leadtimes from config.leadtimes
    #    decoder_variables = bris.routes.get_required_variables(config["routing"])
    decoder_variable_indices = bris.routes.get_variable_indices(config["routing"], datamodule)

    writer = CustomWriter(decoder_outputs, write_interval="batch")

    # Forecaster must know about what leadtimes to output
    model = instantiate(
        config.model,
        checkpoint=checkpoint,
        data_reader=datamodule.data_reader,
        forecast_length=config.leadtimes,
        variable_indices=decoder_variable_indices,
        release_cache=config.release_cache,
    )

    callbacks = list()
    callbacks += [writer]

    inference = Inference(
        config=config,
        model=model,
        callbacks=callbacks,
        checkpoint=checkpoint,
        datamodule=datamodule,
    )
    inference.run()

    # Finalize all output, so they can flush to disk if needed
    is_main_thread = ("SLURM_PROCID" not in os.environ) or (os.environ["SLURM_PROCID"] == "0")
    if is_main_thread:
        for decoder_output in decoder_outputs:
            for output in decoder_output["outputs"]:
                output.finalize()

    print("Hello world")
if __name__ == "__main__":
    main()
