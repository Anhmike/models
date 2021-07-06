from nvtabular.column_group import ColumnGroup
from nvtabular.tag import Tag

from ..tabular import TabularModule
from .continuous import ContinuousFeatures
from .embedding import EmbeddingFeatures


class TabularFeatures(TabularModule):
    def __init__(self, continuous_module=None, categorical_module=None, text_embedding_module=None, aggregation=None):
        super(TabularFeatures, self).__init__()
        self.categorical_module = categorical_module
        self.continuous_module = continuous_module
        self.text_embedding_module = text_embedding_module

        self.to_apply = []
        if continuous_module:
            self.to_apply.append(continuous_module)
        if categorical_module:
            self.to_apply.append(categorical_module)
        if text_embedding_module:
            self.to_apply.append(text_embedding_module)

        assert (self.to_apply is not []), "Please provide at least one input layer"
        self.set_aggregation(aggregation)

    def forward(self, inputs, **kwargs):
        return self.to_apply[0](inputs, merge_with=self.to_apply[1:] if len(self.to_apply) > 1 else None)

    @classmethod
    def from_column_group(cls,
                          column_group: ColumnGroup,
                          continuous_tags=Tag.CONTINUOUS,
                          continuous_tags_to_filter=None,
                          categorical_tags=Tag.CATEGORICAL,
                          categorical_tags_to_filter=None,
                          text_model=None,
                          text_tags=Tag.TEXT_TOKENIZED,
                          text_tags_to_filter=None,
                          max_text_length=None,
                          aggregation=None,
                          **kwargs):
        maybe_continuous_module, maybe_categorical_module = None, None
        if continuous_tags:
            maybe_continuous_module = ContinuousFeatures.from_column_group(
                column_group,
                tags=continuous_tags,
                tags_to_filter=continuous_tags_to_filter)
        if categorical_tags:
            maybe_categorical_module = EmbeddingFeatures.from_column_group(
                column_group,
                tags=categorical_tags,
                tags_to_filter=categorical_tags_to_filter)

        # if text_model and not isinstance(text_model, TransformersTextEmbedding):
        #     text_model = TransformersTextEmbedding.from_column_group(
        #         column_group,
        #         tags=text_tags,
        #         tags_to_filter=text_tags_to_filter,
        #         transformer_model=text_model,
        #         max_text_length=max_text_length)

        return cls(continuous_module=maybe_continuous_module,
                   categorical_module=maybe_categorical_module,
                   text_embedding_module=text_model,
                   aggregation=aggregation)

    def forward_output_size(self, input_size):
        output_sizes = {}
        for in_layer in self.to_apply:
            output_sizes.update(in_layer.forward_output_size(input_size))

        return super().forward_output_size(output_sizes)
