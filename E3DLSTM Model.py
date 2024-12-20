import tensorflow as tf
from tensorflow.keras.layers import LayerNormalization, GlobalAveragePooling3D, Dense, Input
from tensorflow.keras.models import Model
import numpy as np
from google.colab import drive
drive.mount('/content/drive')
path = '/content/drive/MyDrive/alzheimer/'

# Load and preprocess the dataset
def load_data(path, class_dir):
    data = [path + class_dir + '/' + folder + '/temporal_image.nii.gz' for folder in os.listdir(path + class_dir)]
    images = np.array([np.expand_dims(np.transpose(nib.load(img_path).get_fdata().astype(np.float32), (3, 0, 1, 2)), axis=1) for img_path in data])
    labels = np.array([1 if class_dir == 'AD' else (0 if class_dir == 'NC' else 2) for _ in range(len(images))])
    return images, labels

AD_img, AD_label = load_data(path, 'AD')
NC_img, NC_label = load_data(path, 'NC')

# Combine the data and split into train and test sets
l = 115
s = l * 4 // 5

x_train = np.concatenate((AD_img[:s], NC_img[:s]), axis=0)
y_train = np.concatenate((AD_label[:s], NC_label[:s]), axis=0)

x_test = np.concatenate((AD_img[s:], NC_img[s:]), axis=0)
y_test = np.concatenate((AD_label[s:], NC_label[s:]), axis=0)

print(f"x_train: {x_train.shape}, y_train: {y_train.shape}")
print(f"x_test: {x_test.shape}, y_test: {y_test.shape}")




# ConvDeconv3D Module
class ConvDeconv3d(tf.keras.layers.Layer):
    def __init__(self, in_channels, out_channels, kernel_size, **kwargs):
        super(ConvDeconv3d, self).__init__()
        self.conv3d = tf.keras.layers.Conv3D(out_channels, kernel_size, padding='same', **kwargs)
        self.conv_transpose3d = tf.keras.layers.Conv3DTranspose(out_channels, kernel_size, padding='same', **kwargs)

    def call(self, inputs):
        return self.conv_transpose3d(self.conv3d(inputs))

# E3DLSTMCell
class E3DLSTMCell(tf.keras.layers.Layer):
    def __init__(self, input_shape, hidden_size, kernel_size):
        super(E3DLSTMCell, self).__init__()
        in_channels = input_shape[-1]
        self.hidden_size = hidden_size

        # Gates
        self.weight_xi = ConvDeconv3d(in_channels, hidden_size, kernel_size)
        self.weight_hi = ConvDeconv3d(hidden_size, hidden_size, kernel_size, use_bias=False)

        self.weight_xg = ConvDeconv3d(in_channels, hidden_size, kernel_size)
        self.weight_hg = ConvDeconv3d(hidden_size, hidden_size, kernel_size, use_bias=False)

        self.weight_xr = ConvDeconv3d(in_channels, hidden_size, kernel_size)
        self.weight_hr = ConvDeconv3d(hidden_size, hidden_size, kernel_size, use_bias=False)

        self.layer_norm = LayerNormalization()

        self.weight_xo = ConvDeconv3d(in_channels, hidden_size, kernel_size)
        self.weight_ho = ConvDeconv3d(hidden_size, hidden_size, kernel_size, use_bias=False)
        self.weight_co = ConvDeconv3d(hidden_size, hidden_size, kernel_size, use_bias=False)

    def call(self, x, c, h):
        i = tf.sigmoid(self.layer_norm(self.weight_xi(x) + self.weight_hi(h)))
        g = tf.tanh(self.layer_norm(self.weight_xg(x) + self.weight_hg(h)))
        r = tf.sigmoid(self.layer_norm(self.weight_xr(x) + self.weight_hr(h)))
        o = tf.sigmoid(self.layer_norm(self.weight_xo(x) + self.weight_ho(h) + self.weight_co(c)))

        c_next = r * c + i * g
        h_next = o * tf.tanh(c_next)
        return c_next, h_next

# E3DLSTM Layer with Stacking
class E3DLSTM(tf.keras.Model):
    def __init__(self, input_shape, hidden_size, num_layers, kernel_size, num_classes):
        super(E3DLSTM, self).__init__()
        self.layers_stack = [E3DLSTMCell(input_shape, hidden_size, kernel_size) for _ in range(num_layers)]
        self.global_avg_pooling = GlobalAveragePooling3D()
        self.fc = Dense(num_classes, activation='softmax')

    def call(self, x):
        batch_size, seq_len, *dims = x.shape
        c = tf.zeros((batch_size, *dims, self.layers_stack[0].hidden_size), dtype=tf.float32)
        h = tf.zeros((batch_size, *dims, self.layers_stack[0].hidden_size), dtype=tf.float32)

        for layer in self.layers_stack:
            for t in range(seq_len):
                c, h = layer(x[:, t], c, h)

        out = self.global_avg_pooling(h)
        out = self.fc(out)
        return out

# Model parameters
input_shape = (61, 73, 61, 1)  # Shape of a single 3D frame
hidden_size = 64
num_layers = 3
kernel_size = 3
num_classes = 3

# Build the model
input_img = Input(shape=(130, *input_shape))  # 130 timesteps
output = E3DLSTM(input_shape, hidden_size, num_layers, kernel_size, num_classes)(input_img)
model = Model(inputs=input_img, outputs=output)
model.compile(optimizer='adam', loss='sparse_categorical_crossentropy', metrics=['accuracy'])

model.summary()

# Train the model
model.fit(x_train, y_train, epochs=5, batch_size=2, validation_data=(x_test, y_test))

# Evaluate the model
loss, accuracy = model.evaluate(x_test, y_test)
print(f"Test Loss: {loss}, Test Accuracy: {accuracy}")
