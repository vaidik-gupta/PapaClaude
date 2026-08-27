import pytest

from app.content.schema import schema_for
from app.content.tree import ContentTree, Engine, NodeKind


def test_schema_levels_and_data_kind():
    assert schema_for(Engine.DYNAMODB).levels == [NodeKind.GROUP, NodeKind.TABLE, NodeKind.ITEM]
    assert schema_for(Engine.S3).data_kind is NodeKind.OBJECT
    assert schema_for(Engine.MONGODB).is_data(NodeKind.DOCUMENT)
    assert not schema_for(Engine.MONGODB).is_data(NodeKind.COLLECTION)


def test_kind_for_layer_and_too_deep():
    s = schema_for(Engine.DYNAMODB)
    assert s.kind_for_layer(1) is NodeKind.GROUP
    assert s.kind_for_layer(2) is NodeKind.TABLE
    assert s.kind_for_layer(3) is NodeKind.ITEM
    with pytest.raises(ValueError):
        s.kind_for_layer(4)


def test_validate_add_returns_kind():
    t = ContentTree("a")
    s = schema_for(Engine.DYNAMODB)
    assert s.validate_add(t, ["dynamodb", "default"]) is NodeKind.GROUP
    t.add(["dynamodb", "default"], kind=NodeKind.GROUP, owner="a")
    assert s.validate_add(t, ["dynamodb", "default", "orders"]) is NodeKind.TABLE


def test_validate_add_engine_mismatch():
    t = ContentTree("a")
    with pytest.raises(ValueError):
        schema_for(Engine.S3).validate_add(t, ["dynamodb", "default"])


def test_validate_add_missing_parent():
    t = ContentTree("a")
    with pytest.raises(ValueError):
        schema_for(Engine.DYNAMODB).validate_add(t, ["dynamodb", "missing", "orders"])


def test_validate_add_duplicate():
    t = ContentTree("a")
    s = schema_for(Engine.DYNAMODB)
    t.add(["dynamodb", "default"], kind=NodeKind.GROUP, owner="a")
    with pytest.raises(ValueError):
        s.validate_add(t, ["dynamodb", "default"])


def test_validate_add_empty_name():
    t = ContentTree("a")
    with pytest.raises(ValueError):
        schema_for(Engine.DYNAMODB).validate_add(t, ["dynamodb", ""])


def test_validate_delete_rules():
    t = ContentTree("a")
    s = schema_for(Engine.DYNAMODB)
    with pytest.raises(ValueError):
        s.validate_delete(t, ["dynamodb"])          # engine root
    with pytest.raises(ValueError):
        s.validate_delete(t, ["dynamodb", "gone"])  # missing
    t.add(["dynamodb", "default"], kind=NodeKind.GROUP, owner="a")
    s.validate_delete(t, ["dynamodb", "default"])   # valid → no raise
