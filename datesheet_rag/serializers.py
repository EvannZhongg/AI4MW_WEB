
from rest_framework import serializers
from .models import PDFParsingTask

class PDFParsingTaskSerializer(serializers.ModelSerializer):
    pdf_filename = serializers.SerializerMethodField()
    markdown_url = serializers.SerializerMethodField()
    user_username = serializers.CharField(source='user.username', read_only=True)
    # 新增：我们只想显示重复任务的 ID
    duplicate_of_id = serializers.PrimaryKeyRelatedField(
        source='duplicate_of', 
        read_only=True
    )

    class Meta:
        model = PDFParsingTask
        fields = [
            'id', 
            'user_username',
            'pdf_filename', 
            'status', 
            'celery_task_id', 
            'markdown_url', 
            'output_directory',
            'error_message',
            'created_at',
            'updated_at',
            'duplicate_of_id',  # <--- 添加
            'text_preview'      # <--- 添加（可选，用于调试）
        ]
        read_only_fields = [
            'id', 'user_username', 'status', 'celery_task_id', 
            'markdown_url', 'output_directory', 'error_message', 
            'created_at', 'updated_at', 'duplicate_of_id', 'text_preview'
        ]

    def get_pdf_filename(self, obj):
        if obj.pdf_file:
            # 使用我们模型中更新后的方法
            return obj.get_pdf_filename() 
        return None

    def get_markdown_url(self, obj):
        if obj.markdown_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.markdown_file.url)
            return obj.markdown_file.url
        return None