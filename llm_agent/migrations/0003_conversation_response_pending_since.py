from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("llm_agent", "0002_message_attachments_json"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="response_pending_since",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
