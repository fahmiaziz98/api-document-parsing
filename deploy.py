import modal

from src.modal_app import app, image, results_volume


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("parser-secret")],
    volumes={"/results": results_volume},
)
@modal.concurrent(max_inputs=50, target_inputs=10)
@modal.asgi_app()
def web():
    from src.api import web_app

    return web_app
