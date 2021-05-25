def find_start(text, j):
	st = {'\n', '.', '>'}
	ind = next((i for i in range(j-1, -1, -1) if text[i] in st), None)
	if text[ind] == '\n':
		return ind + 1
	else:
		return ind + 2









if __name__ == "__main__":
	print(find_start("df. dfasdfasdf", 5))