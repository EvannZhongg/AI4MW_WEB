from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("llm_agent", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="attachments_json",
            field=models.TextField(blank=True, default=""),
        ),
    ]
