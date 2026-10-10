import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.identity.auth import Organization, User


def _create_organization(session: Session, slug: str, name: str) -> Organization:
    organization = Organization(slug=slug, name=name)
    session.add(organization)
    session.flush()  # 先落库，拿到数据库生成的 id，后面的用户要引用它
    return organization


def _create_user(session: Session, organization: Organization, email: str) -> User:
    user = User(
        org_id=organization.id,
        email=email,
        display_name="集成测试用户",
        password_hash="integration-test-not-a-real-hash",  # 只为满足 NOT NULL，测试不涉及登录
        role="admin",
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def organizations(db_session: Session) -> tuple[Organization, Organization]:
    """两个不同的组织：邮箱唯一约束只在「同一个组织内」生效。"""
    return (
        _create_organization(db_session, slug="it-org-alpha", name="集成测试组织甲"),
        _create_organization(db_session, slug="it-org-beta", name="集成测试组织乙"),
    )


def test_duplicate_email_in_same_organization_is_rejected(
    db_session: Session, organizations: tuple[Organization, Organization]
) -> None:
    """同一个组织内，同一个邮箱插入两次必须被数据库拒绝。"""
    org_alpha, _org_beta = organizations
    email = "duplicate@example.com"

    first_user = _create_user(db_session, org_alpha, email)
    assert first_user.id is not None

    # 用一个保存点包住这次插入：失败后被数据库拒绝，只回滚这一条，不影响前面写入的数据
    savepoint = db_session.begin_nested()
    try:
        with pytest.raises(IntegrityError) as exc_info:
            _create_user(db_session, org_alpha, email)
        # 命中的必须是「组织内邮箱唯一」这条约束，而不是别的原因
        assert "uq_users_org_email" in str(exc_info.value.orig)
    finally:
        savepoint.rollback()

    same_org_users = db_session.execute(
        select(func.count()).select_from(User).where(User.org_id == org_alpha.id)
    ).scalar_one()
    assert same_org_users == 1


def test_same_email_can_be_used_in_different_organizations(
    db_session: Session, organizations: tuple[Organization, Organization]
) -> None:
    """不同组织可以使用同一个邮箱，两个账号都真实写入成功。"""
    org_alpha, org_beta = organizations
    email = "shared@example.com"

    user_alpha = _create_user(db_session, org_alpha, email)
    user_beta = _create_user(db_session, org_beta, email)

    assert user_alpha.id != user_beta.id

    org_ids = db_session.execute(select(User.org_id).where(User.email == email)).scalars().all()
    assert len(org_ids) == 2
    assert set(org_ids) == {user_alpha.org_id, user_beta.org_id}
