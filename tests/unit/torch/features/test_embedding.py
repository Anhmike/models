#
# Copyright (c) 2021, NVIDIA CORPORATION.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from functools import partial

import numpy as np
import pytest
import torch

import merlin.models.torch as ml
from merlin.schema import Tags


def test_embedding_features(torch_cat_features):
    dim = 15
    feature_config = {
        f: ml.FeatureConfig(ml.TableConfig(100, dim, name=f)) for f in torch_cat_features.keys()
    }
    embeddings = ml.EmbeddingFeatures(feature_config)(torch_cat_features)

    assert list(embeddings.keys()) == list(feature_config.keys())
    assert all([emb.shape[-1] == dim for emb in embeddings.values()])


def test_embedding_features_layernorm(torch_cat_features):
    dim = 15
    feature_config = {
        f: ml.FeatureConfig(ml.TableConfig(100, dim, name=f)) for f in torch_cat_features.keys()
    }

    layer_norm = ml.TabularLayerNorm.from_feature_config(feature_config)
    embeddings = ml.EmbeddingFeatures(feature_config, post=layer_norm)(torch_cat_features)
    assert all(
        [emb.detach().numpy().mean() == pytest.approx(0.0, abs=0.1) for emb in embeddings.values()]
    )
    assert all([emb.detach().numpy().std() > 0.5 for emb in embeddings.values()])


def test_embedding_features_custom_init(torch_cat_features):
    MEAN = 1.0
    STD = 0.05
    emb_initializer = partial(torch.nn.init.normal_, mean=MEAN, std=STD)
    feature_config = {
        f: ml.FeatureConfig(ml.TableConfig(100, dim=15, name=f, initializer=emb_initializer))
        for f in torch_cat_features.keys()
    }
    embeddings = ml.EmbeddingFeatures(feature_config)(torch_cat_features)

    assert list(embeddings.keys()) == list(feature_config.keys())
    assert all(
        [emb.detach().numpy().mean() == pytest.approx(MEAN, abs=0.1) for emb in embeddings.values()]
    )
    assert all(
        [emb.detach().numpy().std() == pytest.approx(STD, abs=0.1) for emb in embeddings.values()]
    )


def test_table_config_invalid_embedding_initializer():
    with pytest.raises(ValueError) as excinfo:
        ml.TableConfig(100, dim=15, initializer="INVALID INITIALIZER")
    assert "initializer must be callable if specified" in str(excinfo.value)


def test_embedding_features_yoochoose(tabular_schema, torch_tabular_data):
    schema = tabular_schema.select_by_tag(Tags.CATEGORICAL)

    emb_module = ml.EmbeddingFeatures.from_schema(schema)
    embeddings = emb_module(torch_tabular_data)

    assert sorted(list(embeddings.keys())) == sorted(schema.column_names)
    assert all(emb.shape[-1] == 64 for emb in embeddings.values())
    assert emb_module.item_id == "item_id"

    max_value = list(schema.select_by_name("item_id"))[0].int_domain.max
    assert emb_module.item_embedding_table.num_embeddings == max_value + 1


def test_embedding_features_yoochoose_custom_dims(tabular_schema, torch_tabular_data):
    schema = tabular_schema.select_by_tag(Tags.CATEGORICAL)

    emb_module = ml.EmbeddingFeatures.from_schema(
        schema, embedding_dims={"item_id": 100}, embedding_dim_default=64
    )

    assert emb_module.embedding_tables["item_id"].weight.shape[1] == 100
    assert emb_module.embedding_tables["categories"].weight.shape[1] == 64

    embeddings = emb_module(torch_tabular_data)

    assert embeddings["item_id"].shape[1] == 100
    assert embeddings["categories"].shape[1] == 64


def test_embedding_features_yoochoose_infer_embedding_sizes(tabular_schema, torch_tabular_data):
    schema = tabular_schema.select_by_tag(Tags.CATEGORICAL)

    emb_module = ml.EmbeddingFeatures.from_schema(
        schema, infer_embedding_sizes=True, infer_embedding_sizes_multiplier=3.0
    )

    assert emb_module.embedding_tables["item_id"].weight.shape[1] == 46
    assert emb_module.embedding_tables["categories"].weight.shape[1] == 13

    embeddings = emb_module(torch_tabular_data)

    assert embeddings["item_id"].shape[1] == 46
    assert embeddings["categories"].shape[1] == 13


def test_embedding_features_yoochoose_custom_initializers(tabular_schema, torch_tabular_data):
    ITEM_MEAN = 1.0
    ITEM_STD = 0.05

    CATEGORY_MEAN = 2.0
    CATEGORY_STD = 0.1

    schema = tabular_schema.select_by_tag(Tags.CATEGORICAL)
    emb_module = ml.EmbeddingFeatures.from_schema(
        schema,
        layer_norm=False,
        embeddings_initializers={
            "item_id": partial(torch.nn.init.normal_, mean=ITEM_MEAN, std=ITEM_STD),
            "categories": partial(torch.nn.init.normal_, mean=CATEGORY_MEAN, std=CATEGORY_STD),
        },
    )

    embeddings = emb_module(torch_tabular_data)

    assert embeddings["item_id"].detach().numpy().mean() == pytest.approx(ITEM_MEAN, abs=0.1)
    assert embeddings["item_id"].detach().numpy().std() == pytest.approx(ITEM_STD, abs=0.1)

    assert embeddings["categories"].detach().numpy().mean() == pytest.approx(CATEGORY_MEAN, abs=0.1)
    assert embeddings["categories"].detach().numpy().std() == pytest.approx(CATEGORY_STD, abs=0.1)


def test_soft_embedding_invalid_num_embeddings():
    with pytest.raises(AssertionError) as excinfo:
        ml.SoftEmbedding(num_embeddings=0, embeddings_dim=16)
    assert "number of embeddings for soft embeddings needs to be greater than 0" in str(
        excinfo.value
    )


def test_soft_embedding_invalid_embeddings_dim():
    with pytest.raises(AssertionError) as excinfo:
        ml.SoftEmbedding(num_embeddings=10, embeddings_dim=0)
    assert "embeddings dim for soft embeddings needs to be greater than 0" in str(excinfo.value)


def test_soft_embedding():
    torch.manual_seed(0)
    embeddings_dim = 16
    num_embeddings = 64

    soft_embedding = ml.SoftEmbedding(num_embeddings, embeddings_dim)
    assert soft_embedding.embedding_table.weight.shape == torch.Size(
        [num_embeddings, embeddings_dim]
    ), "Internal soft embedding table does not have the expected shape"

    batch_size = 10
    seq_length = 20
    cont_feature_inputs = torch.rand((batch_size, seq_length))
    output = soft_embedding(cont_feature_inputs)

    assert output.shape == torch.Size(
        [batch_size, seq_length, embeddings_dim]
    ), "Soft embedding output has not the expected shape"

    # Checking the default embedding initialization
    assert output.detach().numpy().mean() == pytest.approx(0.0, abs=0.1)
    assert output.detach().numpy().std() == pytest.approx(0.05, abs=0.2)


def test_soft_embedding_with_custom_init():
    embeddings_dim = 16
    num_embeddings = 64

    INIT_MEAN = 1.0
    INIT_STD = 0.05
    emb_initializer = partial(torch.nn.init.normal_, mean=INIT_MEAN, std=INIT_STD)
    soft_embedding = ml.SoftEmbedding(
        num_embeddings, embeddings_dim, emb_initializer=emb_initializer
    )
    assert soft_embedding.embedding_table.weight.shape == torch.Size(
        [num_embeddings, embeddings_dim]
    ), "Internal soft embedding table does not have the expected shape"

    batch_size = 10
    seq_length = 20
    cont_feature_inputs = torch.rand((batch_size, seq_length))
    output = soft_embedding(cont_feature_inputs)

    assert output.shape == torch.Size(
        [batch_size, seq_length, embeddings_dim]
    ), "Soft embedding output has not the expected shape"

    assert output.detach().numpy().mean() == pytest.approx(INIT_MEAN, abs=0.1)
    assert output.detach().numpy().std() == pytest.approx(INIT_STD, abs=0.1)


def test_soft_continuous_features(torch_con_features):
    dim = 16
    num_embeddings = 64

    emb_initializer = partial(torch.nn.init.normal_, mean=1.0, std=0.05)

    feature_config = {
        f: ml.FeatureConfig(
            ml.TableConfig(num_embeddings, dim, initializer=emb_initializer, name=f)
        )
        for f in torch_con_features.keys()
    }

    soft_embeddings = ml.SoftEmbeddingFeatures(feature_config)
    output = soft_embeddings(torch_con_features)

    assert list(output.keys()) == list(feature_config.keys())
    assert all(
        [list(v.shape) == list(torch_con_features[k].shape) + [dim] for k, v in output.items()]
    )


def test_layer_norm_features():
    ln = ml.TabularLayerNorm(features_dim={"a": 100, "b": 200})
    inputs = {
        "a": torch.tensor(np.random.uniform(1.0, 4.0, (500, 100)), dtype=torch.float32),
        "b": torch.tensor(np.random.uniform(2.0, 10.0, (500, 200)), dtype=torch.float32),
    }

    outputs = ln(inputs)

    assert all(
        [val.detach().numpy().mean() == pytest.approx(0.0, abs=0.1) for val in outputs.values()]
    )
    assert all(
        [val.detach().numpy().std() == pytest.approx(1.0, abs=0.1) for val in outputs.values()]
    )
