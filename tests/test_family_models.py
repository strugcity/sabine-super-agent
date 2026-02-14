"""
Tests for lib.db.family_models and lib.db.family_graph_loader
================================================================

Covers Pydantic model validation, keyword matching, family member
inference, and the synchronous load_seed_file helper.
"""

import uuid
from typing import Optional

import pytest
from pydantic import ValidationError

from lib.db.family_models import (
    CalendarKeywords,
    FamilyContext,
    FamilyMember,
    FamilyMemberProfile,
    KeywordCategory,
    KeywordMapping,
    RelationshipType,
    create_family_member_entity_dict,
)
from lib.db.family_graph_loader import _parse_profile


# =========================================================================
# KeywordMapping
# =========================================================================

class TestKeywordMapping:

    def test_basic_creation(self) -> None:
        km = KeywordMapping(keywords=["btba", "bandits"])
        assert km.keywords == ["btba", "bandits"]
        assert km.weight == 1.0

    def test_keywords_normalised_to_lowercase(self) -> None:
        km = KeywordMapping(keywords=["BTBA", "  Bandits  "])
        assert km.keywords == ["btba", "bandits"]

    def test_empty_strings_stripped(self) -> None:
        km = KeywordMapping(keywords=["valid", "", "  "])
        assert km.keywords == ["valid"]

    def test_weight_range(self) -> None:
        km = KeywordMapping(keywords=["a"], weight=0.0)
        assert km.weight == 0.0
        km2 = KeywordMapping(keywords=["a"], weight=2.0)
        assert km2.weight == 2.0

    def test_weight_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            KeywordMapping(keywords=["a"], weight=3.0)


# =========================================================================
# CalendarKeywords
# =========================================================================

class TestCalendarKeywords:

    def test_empty_defaults(self) -> None:
        ck = CalendarKeywords()
        assert ck.all_keywords() == {}

    def test_all_keywords_aggregates_categories(self) -> None:
        ck = CalendarKeywords(
            sports=KeywordMapping(keywords=["baseball"]),
            school=KeywordMapping(keywords=["jefferson"]),
        )
        all_kw = ck.all_keywords()
        assert "sports" in all_kw
        assert "school" in all_kw
        assert len(all_kw) == 2

    def test_extra_categories(self) -> None:
        ck = CalendarKeywords(
            extra={"music": KeywordMapping(keywords=["piano", "recital"])},
        )
        all_kw = ck.all_keywords()
        assert "music" in all_kw

    def test_find_matches_single(self) -> None:
        ck = CalendarKeywords(
            sports=KeywordMapping(keywords=["btba", "bandits"], weight=1.0),
        )
        matches = ck.find_matches("BTBA Bandits practice Tuesday")
        assert len(matches) == 2
        assert all(m[0] == "sports" for m in matches)

    def test_find_matches_no_match(self) -> None:
        ck = CalendarKeywords(
            sports=KeywordMapping(keywords=["btba"]),
        )
        matches = ck.find_matches("Piano recital at 3pm")
        assert matches == []


# =========================================================================
# FamilyMemberProfile
# =========================================================================

class TestFamilyMemberProfile:

    def test_defaults(self) -> None:
        p = FamilyMemberProfile()
        assert p.relationship == RelationshipType.CHILD
        assert p.schools == []

    def test_full_profile(self) -> None:
        p = FamilyMemberProfile(
            age=14,
            grade="9th",
            birthday="03-15",
            relationship=RelationshipType.CHILD,
            schools=["Jefferson High"],
            teams=["BTBA Bandits"],
        )
        assert p.age == 14

    def test_age_validation(self) -> None:
        with pytest.raises(ValidationError):
            FamilyMemberProfile(age=-1)


# =========================================================================
# FamilyContext + inference
# =========================================================================

class TestFamilyContext:

    def _make_context(self) -> FamilyContext:
        jack = FamilyMember(
            entity_id=uuid.uuid4(),
            name="Jack",
            profile=FamilyMemberProfile(
                calendar_keywords=CalendarKeywords(
                    sports=KeywordMapping(keywords=["btba", "bandits", "baseball"], weight=1.0),
                    school=KeywordMapping(keywords=["jefferson", "jhs"], weight=0.8),
                ),
            ),
        )
        anna = FamilyMember(
            entity_id=uuid.uuid4(),
            name="Anna",
            profile=FamilyMemberProfile(
                calendar_keywords=CalendarKeywords(
                    activities=KeywordMapping(keywords=["dance", "ballet"], weight=1.0),
                    school=KeywordMapping(keywords=["lincoln", "lms"], weight=0.8),
                ),
            ),
        )
        return FamilyContext(members=[jack, anna])

    def test_get_member_by_name(self) -> None:
        ctx = self._make_context()
        assert ctx.get_member_by_name("Jack") is not None
        assert ctx.get_member_by_name("jack") is not None
        assert ctx.get_member_by_name("Charlie") is None

    def test_infer_owner_jack(self) -> None:
        ctx = self._make_context()
        member, confidence, evidence = ctx.infer_owner("BTBA Bandits practice")
        assert member is not None
        assert member.name == "Jack"
        assert confidence > 0.0
        assert len(evidence) > 0

    def test_infer_owner_anna(self) -> None:
        ctx = self._make_context()
        member, confidence, evidence = ctx.infer_owner("Ballet recital dance")
        assert member is not None
        assert member.name == "Anna"

    def test_infer_owner_no_match(self) -> None:
        ctx = self._make_context()
        member, confidence, evidence = ctx.infer_owner("Doctor appointment")
        assert member is None
        assert confidence == 0.0
        assert evidence == []

    def test_infer_owner_returns_higher_confidence_match(self) -> None:
        ctx = self._make_context()
        # "btba bandits baseball" hits 3 keywords for Jack
        member, confidence, evidence = ctx.infer_owner("btba bandits baseball game")
        assert member is not None
        assert member.name == "Jack"
        assert confidence >= 0.5


# =========================================================================
# create_family_member_entity_dict
# =========================================================================

class TestCreateEntityDict:

    def test_output_structure(self) -> None:
        profile = FamilyMemberProfile(age=10, relationship=RelationshipType.CHILD)
        d = create_family_member_entity_dict("Jack", profile)
        assert d["name"] == "Jack"
        assert d["type"] == "family_member"
        assert d["domain"] == "family"
        assert d["status"] == "active"
        assert isinstance(d["attributes"], dict)


# =========================================================================
# _parse_profile (from family_graph_loader)
# =========================================================================

class TestParseProfile:

    def test_empty_attributes(self) -> None:
        p = _parse_profile({})
        assert isinstance(p, FamilyMemberProfile)

    def test_with_calendar_keywords(self) -> None:
        attrs = {
            "age": 14,
            "grade": "9th",
            "calendar_keywords": {
                "sports": {"keywords": ["btba"], "weight": 1.0},
            },
        }
        p = _parse_profile(attrs)
        assert p.age == 14
        assert p.calendar_keywords.sports is not None
        assert "btba" in p.calendar_keywords.sports.keywords

    def test_extra_categories_parsed(self) -> None:
        attrs = {
            "calendar_keywords": {
                "music": {"keywords": ["piano"], "weight": 0.5},
            },
        }
        p = _parse_profile(attrs)
        assert "music" in p.calendar_keywords.extra
