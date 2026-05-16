from tictactoe.render import render_board_png_base64

b64 = render_board_png_base64({
    "0:0": "circle",
    "1:1": "cross",
    "2:2": "circle",
})

print(b64)