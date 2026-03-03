A program intended to provide insight into draft strength and to help give ideas for champs to select during champ select.

draftsmith.py contains the code that is executed by draftsmith.exe.
DatasetCreator.ipynb contains the code used to retreieve ranked game data to create a dataset. It also contains a clearer look at how the exe functions. 

The program takes in data from both professional game datasets and ranked game datasets. It connects to the client and uses machine learning to rate your current draft with probability of a win, based on training data.
The second phase, looks at your remaining roles to be filled and then uses statistics from pro and ranked as to comeup with a top 20 list, then uses machine learning to see which picks work best in your current draft.

To use, simply download the folder and run the draftsmith.exe and input your lockfile location.
