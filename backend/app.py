from portal import create_app

app = create_app()

if __name__ == '__main__':
    # threaded=True so the live monitor's polling never waits behind a slow request
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
