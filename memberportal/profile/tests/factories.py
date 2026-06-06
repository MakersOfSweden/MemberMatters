import factory
from django.contrib.auth import get_user_model

from profile.models import Profile

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@test.com")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        password = kwargs.pop("password", "pw")
        user = model_class.objects.create_user(password=password, **kwargs)
        return user


class MemberFactory(UserFactory):
    email = factory.Sequence(lambda n: f"member{n}@test.com")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        user = super()._create(model_class, *args, **kwargs)
        Profile.objects.create(
            user=user,
            screen_name="Test",
            first_name="Test",
            last_name="Member",
        )
        return user
