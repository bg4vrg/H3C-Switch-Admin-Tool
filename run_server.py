from waitress import serve
from app import app  # 导入你的 Flask app 对象

if __name__ == '__main__':
    print("服务已启动: http://0.0.0.0:8080")
    # threads=4 表示允许4个人同时操作，避免卡顿
    serve(app, host='0.0.0.0', port=8080, threads=4)